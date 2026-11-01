#!/bin/sh
# Respaldo local de GuauWoow (contenedor "backup": postgres:16 + openssl).
#
#   backup.sh            -> un respaldo completo (base + fotos)
#   backup.sh db         -> solo la base        backup.sh uploads -> solo las fotos
#   backup.sh loop       -> servicio: revisa el disco cada DISK_CHECK_INTERVAL_SECONDS (1 h) y
#                           respalda una vez al día a partir de BACKUP_HOUR (3 h, hora de TZ)
#   backup.sh health     -> healthcheck de Docker (0 = sano)
#   BACKUP_ADHOC=1 backup.sh db -> dump extra (p. ej. antes de migrar en deploy.sh): no cambia las
#                           marcas del servicio diario ni avisa al heartbeat
#
# Qué queda en BACKUP_DIR (/backups = ./backups en el host):
#   db/db-AAAAMMDD-HHMMSS.dump.enc  pg_dump -Fc cifrado con openssl (AES-256, PBKDF2) usando
#                                   BACKUP_ENCRYPTION_PASSWORD; se conservan BACKUP_RETENTION_DAYS (14)
#   uploads/AAAAMMDD-HHMMSS/        instantánea de las fotos (incluye private/). Los archivos que no
#                                   cambiaron son enlaces duros a la instantánea anterior, así que cada
#                                   día solo ocupa lo nuevo. Se excluyen las carpetas .pre-restore-*.
#   .state/                         marcas de la última corrida (las usa health y el loop)
# Las instantáneas de fotos viven en el mismo disco: protegen contra borrados, no contra perder el
# disco. Para eso está la copia externa cifrada (backup-offsite.sh, BACKUP_S3_BUCKET).
#
# Variables: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, BACKUP_ENCRYPTION_PASSWORD,
#   BACKUP_REQUIRE_ENCRYPTION (true en producción), BACKUP_RETENTION_DAYS, BACKUP_HOUR,
#   BACKUP_INTERVAL_SECONDS, BACKUP_HEARTBEAT_URL, BACKUP_S3_BUCKET, DISK_* (disk-check.sh)
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_TAG=backup
. "$SCRIPT_DIR/lib-backup.sh"

BACKUP_DIR=${BACKUP_DIR:-/backups}
UPLOADS_DIR=${UPLOADS_DIR:-/uploads}
RETENTION=${BACKUP_RETENTION_DAYS:-14}
MIN_KEEP=${BACKUP_MIN_KEEP:-3}            # nunca se borran los N respaldos más recientes
INTERVAL=${BACKUP_INTERVAL_SECONDS:-86400}
BACKUP_HOUR=${BACKUP_HOUR-3}              # vacío = cada BACKUP_INTERVAL_SECONDS desde el último
CHECK_INTERVAL=${DISK_CHECK_INTERVAL_SECONDS:-3600}
DB_DIR="$BACKUP_DIR/db"
SNAP_DIR="$BACKUP_DIR/uploads"
STATE_DIR="$BACKUP_DIR/.state"

encryption_enabled() {
  [ -n "${BACKUP_ENCRYPTION_PASSWORD:-}" ]
}

require_encryption() {
  if ! encryption_enabled && [ "${BACKUP_REQUIRE_ENCRYPTION:-false}" = "true" ]; then
    warn "ERROR: BACKUP_ENCRYPTION_PASSWORD está vacío y BACKUP_REQUIRE_ENCRYPTION=true; no se respalda sin cifrar."
    return 1
  fi
  if ! encryption_enabled; then
    warn "AVISO: BACKUP_ENCRYPTION_PASSWORD vacío: el dump queda SIN cifrar (solo aceptable en desarrollo)."
  fi
}

# ------------------------------------------------------------------ base de datos
backup_db() {
  # (set -e no aplica dentro de "f || x": cada paso crítico se revisa a mano)
  ts=$1
  require_encryption || return 1
  mkdir -p "$DB_DIR" || return 1
  rm -f "$DB_DIR"/*.partial
  out="$DB_DIR/db-$ts.dump"
  if encryption_enabled; then
    out="$out.enc"
    rc_file="$STATE_DIR/pg_dump.failed"
    rm -f "$rc_file"
    # sh no tiene pipefail: si pg_dump falla deja una marca
    # shellcheck disable=SC2086
    { pg_dump -Fc --no-owner || echo "$?" > "$rc_file"; } \
      | openssl enc $OPENSSL_ENC_ARGS -pass env:BACKUP_ENCRYPTION_PASSWORD -out "$out.partial" || {
        rm -f "$out.partial"; warn "ERROR: openssl no pudo cifrar el dump"; return 1; }
    if [ -f "$rc_file" ]; then
      rm -f "$rc_file" "$out.partial"
      warn "ERROR: pg_dump falló"
      return 1
    fi
    # Verificación: se descifra y pg_restore lee el índice del archivo
    # shellcheck disable=SC2086
    if ! openssl enc -d $OPENSSL_ENC_ARGS -pass env:BACKUP_ENCRYPTION_PASSWORD -in "$out.partial" 2>/dev/null \
        | pg_restore --list >/dev/null; then
      rm -f "$out.partial"
      warn "ERROR: el dump cifrado no se pudo verificar"
      return 1
    fi
  else
    pg_dump -Fc --no-owner -f "$out.partial" || { rm -f "$out.partial"; warn "ERROR: pg_dump falló"; return 1; }
    pg_restore --list "$out.partial" >/dev/null || { rm -f "$out.partial"; warn "ERROR: el dump no se pudo verificar"; return 1; }
  fi
  chmod 600 "$out.partial" && mv "$out.partial" "$out" || return 1
  log "base respaldada: $out ($(du -h "$out" | cut -f1))"
}

prune_db() {
  # Más recientes primero; se conservan siempre los MIN_KEEP más nuevos
  cutoff=$(stamp_days_ago "$RETENTION")
  n=0
  for f in $(list_names "$DB_DIR" '^db-[0-9]{8}-[0-9]{6}\.dump(\.enc)?$' | sort -r); do
    n=$((n + 1))
    [ "$n" -le "$MIN_KEEP" ] && continue
    stamp=$(echo "$f" | sed -E 's/^db-([0-9]{8}-[0-9]{6}).*/\1/')
    if stamp_before "$stamp" "$cutoff"; then
      rm -f "$DB_DIR/$f" && log "retención: borrado db/$f"
    fi
  done
  # Formato anterior (db-*.dump y uploads-*.tar.gz en la raíz de /backups): caducan solos
  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' -o -name '*.partial' \) \
    -mtime +"$RETENTION" -print -delete 2>/dev/null || true
}

# ------------------------------------------------------------------ fotos (instantáneas incrementales)
latest_snapshot() {
  list_names "$SNAP_DIR" '^[0-9]{8}-[0-9]{6}$' | sort | tail -1
}

backup_uploads() {
  ts=$1
  if [ ! -d "$UPLOADS_DIR" ]; then
    warn "no existe $UPLOADS_DIR; se omiten las fotos"
    return 0
  fi
  mkdir -p "$SNAP_DIR" "$STATE_DIR" || return 1
  rm -rf "$SNAP_DIR"/*.partial
  if [ -e "$SNAP_DIR/$ts" ]; then
    warn "ERROR: ya existe uploads/$ts (dos respaldos en el mismo segundo); inténtalo de nuevo"
    return 1
  fi
  tmp="$SNAP_DIR/$ts.partial"
  prev=$(latest_snapshot)
  if [ -n "$prev" ]; then
    # Copia de enlaces duros (no ocupa espacio) de la instantánea anterior, en el mismo disco
    cp -al "$SNAP_DIR/$prev" "$tmp" || { warn "ERROR: no se pudo copiar uploads/$prev"; return 1; }
  else
    mkdir -p "$tmp" || return 1
  fi
  copied=0
  # 1) archivos nuevos o modificados (se rompe el enlace antes de copiar para no tocar la anterior)
  list="$STATE_DIR/uploads.list"
  (cd "$UPLOADS_DIR" && find . -path './.pre-restore-*' -prune -o \( -type f ! -name '.write-test' -print \)) > "$list" \
    || { warn "ERROR: no se pudo leer $UPLOADS_DIR"; return 1; }
  while IFS= read -r f; do
    src="$UPLOADS_DIR/${f#./}"
    dst="$tmp/${f#./}"
    # shellcheck disable=SC3013  # -nt no es POSIX, pero dash (Debian) y busybox (alpine) lo soportan
    if [ -f "$dst" ] && [ ! "$src" -nt "$dst" ]; then
      continue
    fi
    if ! { mkdir -p "$(dirname "$dst")" && rm -f "$dst" && cp -p "$src" "$dst"; }; then
      warn "ERROR: no se pudo copiar $f"
      return 1
    fi
    copied=$((copied + 1))
  done < "$list"
  # 2) archivos que ya no existen en el origen
  removed=0
  (cd "$tmp" && find . -type f -print) > "$list" || return 1
  while IFS= read -r f; do
    if [ ! -e "$UPLOADS_DIR/${f#./}" ]; then
      rm -f "$tmp/${f#./}"
      removed=$((removed + 1))
    fi
  done < "$list"
  rm -f "$list"
  mv "$tmp" "$SNAP_DIR/$ts" || return 1
  total=$(find "$SNAP_DIR/$ts" -type f | wc -l | tr -d ' ')
  log "fotos respaldadas: uploads/$ts ($total archivos; $copied nuevos o cambiados, $removed borrados desde ${prev:-cero})"
}

prune_uploads() {
  cutoff=$(stamp_days_ago "$RETENTION")
  n=0
  for d in $(list_names "$SNAP_DIR" '^[0-9]{8}-[0-9]{6}$' | sort -r); do
    n=$((n + 1))
    [ "$n" -le "$MIN_KEEP" ] && continue
    if stamp_before "$d" "$cutoff"; then
      rm -rf "${SNAP_DIR:?}/$d" && log "retención: borrada uploads/$d"
    fi
  done
}

# ------------------------------------------------------------------ orquestación
offsite_warning() {
  if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
    loud_warning \
      "SIN COPIA EXTERNA: BACKUP_S3_BUCKET está vacío." \
      "Los respaldos viven en el MISMO disco que la base y las fotos: si el servidor" \
      "o el disco se pierden, se pierde todo. Configura BACKUP_S3_* (Cloudflare R2/S3)." \
      "Ver docs/operacion.md, sección Respaldos."
  fi
}

run_backup() {
  what=${1:-all}
  mkdir -p "$STATE_DIR"
  ts=$(date +%Y%m%d-%H%M%S)
  if [ "${BACKUP_ADHOC:-0}" = "1" ]; then
    log "respaldo extra $ts ($what)"
    if [ "$what" = all ] || [ "$what" = db ]; then backup_db "$ts" || return 1; fi
    if [ "$what" = all ] || [ "$what" = uploads ]; then backup_uploads "$ts" || return 1; fi
    return 0
  fi
  touch "$STATE_DIR/started.tmp"
  heartbeat "${BACKUP_HEARTBEAT_URL:-}" start
  log "iniciando respaldo $ts ($what)"
  errfile="$STATE_DIR/last-error.log"
  : > "$errfile"
  status=0
  if [ "$what" = all ] || [ "$what" = db ]; then
    { backup_db "$ts" && prune_db; } 2>>"$errfile" || status=1
  fi
  if [ "$what" = all ] || [ "$what" = uploads ]; then
    { backup_uploads "$ts" && prune_uploads; } 2>>"$errfile" || status=1
  fi
  [ -s "$errfile" ] && cat "$errfile" >&2
  offsite_warning
  if [ "$status" -eq 0 ]; then
    # Solo un respaldo completo cuenta como "el del día" para el servicio diario
    if [ "$what" = all ]; then
      mv "$STATE_DIR/started.tmp" "$STATE_DIR/last-success"
    else
      rm -f "$STATE_DIR/started.tmp"
    fi
    summary="respaldo $ts correcto; db: $(list_names "$DB_DIR" '^db-' | wc -l | tr -d ' ') dumps, fotos: $(latest_snapshot)"
    [ -z "${BACKUP_S3_BUCKET:-}" ] && summary="$summary. ADVERTENCIA: sin copia externa (BACKUP_S3_BUCKET vacío)"
    log "listo: $summary"
    heartbeat "${BACKUP_HEARTBEAT_URL:-}" ok "$summary"
  else
    rm -f "$STATE_DIR/started.tmp"
    touch "$STATE_DIR/last-failure"
    warn "ERROR: el respaldo $ts falló"
    heartbeat "${BACKUP_HEARTBEAT_URL:-}" fail "respaldo $ts falló: $(tail -c 2000 "$errfile")"
  fi
  return "$status"
}

health() {
  hb="$STATE_DIR/loop-heartbeat"
  age=$(file_age "$hb") || { echo "el ciclo de respaldo no ha arrancado"; exit 1; }
  if [ "$age" -gt $((CHECK_INTERVAL * 2 + 600)) ]; then
    echo "el ciclo de respaldo no avanza (última vuelta hace ${age}s)"
    exit 1
  fi
  # shellcheck disable=SC3013  # -nt: lo soportan dash y busybox
  if [ -f "$STATE_DIR/last-failure" ] && { [ ! -f "$STATE_DIR/last-success" ] \
      || [ "$STATE_DIR/last-failure" -nt "$STATE_DIR/last-success" ]; }; then
    echo "el último respaldo falló (ver: docker compose logs backup)"
    exit 1
  fi
  if ok_age=$(file_age "$STATE_DIR/last-success"); then
    if [ "$ok_age" -gt $((INTERVAL * 2 + 3600)) ]; then
      echo "el último respaldo exitoso fue hace ${ok_age}s"
      exit 1
    fi
  fi
  echo "ok"
  exit 0
}

loop() {
  mkdir -p "$STATE_DIR"
  log "servicio de respaldo: diario desde las ${BACKUP_HOUR:-(cada ${INTERVAL}s)} h, retención ${RETENTION} días, disco cada ${CHECK_INTERVAL}s"
  if ! require_encryption; then
    heartbeat "${BACKUP_HEARTBEAT_URL:-}" fail "BACKUP_ENCRYPTION_PASSWORD vacío: no se respalda"
    exit 1
  fi
  offsite_warning
  sleep "${BACKUP_START_DELAY_SECONDS:-15}"   # deja que PostgreSQL termine de arrancar
  while :; do
    touch "$STATE_DIR/loop-heartbeat"
    sh "$SCRIPT_DIR/disk-check.sh" || true
    if is_due "$STATE_DIR/last-success" "$BACKUP_HOUR" "$INTERVAL"; then
      run_backup all || true
    fi
    sleep "$CHECK_INTERVAL"
  done
}

case "${1:-all}" in
  loop) loop ;;
  health) health ;;
  all | db | uploads) run_backup "${1:-all}" ;;
  *)
    echo "Uso: backup.sh [all|db|uploads|loop|health]" >&2
    exit 2
    ;;
esac
