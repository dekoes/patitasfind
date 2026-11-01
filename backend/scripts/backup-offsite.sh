#!/bin/sh
# Copia externa CIFRADA de GuauWoow a S3 / Cloudflare R2 con rclone (contenedor "backup-offsite").
#
#   backup-offsite.sh          -> servicio: corre una vez al día a partir de BACKUP_OFFSITE_HOUR (4 h)
#   backup-offsite.sh once     -> una corrida ahora        backup-offsite.sh health -> healthcheck
#
# El remote "offsite" (s3) se define con RCLONE_CONFIG_OFFSITE_* (docker-compose.production.yml).
# Aquí se arma encima el remote cifrado "offsitecrypt" (rclone crypt: contenido y nombres cifrados)
# con BACKUP_ENCRYPTION_PASSWORD y BACKUP_ENCRYPTION_SALT. Sin AMBOS valores no se puede leer la copia:
# guárdalos fuera del servidor.
#
# En el bucket (dentro de BACKUP_S3_PREFIX, todo cifrado):
#   db/                     dumps de /backups/db (ya cifrados con openssl); se borran los de más de
#                           BACKUP_OFFSITE_RETENTION_DAYS (30)
#   uploads/current/        espejo de las fotos (incluye private/); solo sube lo nuevo
#   uploads/archive/<fecha>/ lo que se borró o cambió en esa corrida; se conserva el mismo plazo
#
# Para bajar algo (en el servidor), "rclone ..." con el remote cifrado ya configurado:
#   docker compose -f docker-compose.production.yml run --rm -v "$PWD/backups/restore:/restore" \
#     --entrypoint sh backup-offsite /scripts/backup-offsite.sh rclone copy offsitecrypt:db /restore/db --max-age 3d
# (ver docs/operacion.md: restaurar desde la copia externa)
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_TAG=offsite
. "$SCRIPT_DIR/lib-backup.sh"

INTERVAL=${BACKUP_INTERVAL_SECONDS:-86400}
OFFSITE_HOUR=${BACKUP_OFFSITE_HOUR-4}
RETENTION=${BACKUP_OFFSITE_RETENTION_DAYS:-30}
STATE_DIR=${OFFSITE_STATE_DIR:-/tmp/offsite-state}
DB_SRC=${BACKUP_DIR:-/backups}/db
UPLOADS_SRC=${UPLOADS_DIR:-/uploads}
RCLONE_FLAGS="--transfers ${BACKUP_OFFSITE_TRANSFERS:-4} --checkers 8 --log-level NOTICE"

enabled() {
  [ -n "${BACKUP_S3_BUCKET:-}" ]
}

# Configura el remote cifrado (exporta variables RCLONE_CONFIG_OFFSITECRYPT_*)
setup_crypt() {
  if [ -z "${RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID:-}" ] || [ -z "${RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY:-}" ]; then
    warn "Faltan BACKUP_S3_ACCESS_KEY_ID / BACKUP_S3_SECRET_ACCESS_KEY."
    return 1
  fi
  if [ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]; then
    warn "Falta BACKUP_ENCRYPTION_PASSWORD: la copia externa nunca se sube sin cifrar."
    return 1
  fi
  if [ -z "${BACKUP_ENCRYPTION_SALT:-}" ]; then
    warn "AVISO: BACKUP_ENCRYPTION_SALT vacío; se cifra solo con la contraseña (define una sal aleatoria)."
  fi
  # Todo se configura por variables; un archivo vacío evita el aviso "config file not found"
  export RCLONE_CONFIG="${RCLONE_CONFIG_FILE:-/tmp/rclone.conf}"
  [ -f "$RCLONE_CONFIG" ] || : > "$RCLONE_CONFIG"
  export RCLONE_CONFIG_OFFSITECRYPT_TYPE=crypt
  export RCLONE_CONFIG_OFFSITECRYPT_REMOTE="offsite:${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-patitasfind}"
  export RCLONE_CONFIG_OFFSITECRYPT_FILENAME_ENCRYPTION=standard
  export RCLONE_CONFIG_OFFSITECRYPT_DIRECTORY_NAME_ENCRYPTION=true
  # rclone exige las contraseñas "ofuscadas"; se leen por stdin para que no aparezcan en ps
  RCLONE_CONFIG_OFFSITECRYPT_PASSWORD=$(printf '%s' "$BACKUP_ENCRYPTION_PASSWORD" | rclone obscure -) || return 1
  export RCLONE_CONFIG_OFFSITECRYPT_PASSWORD
  if [ -n "${BACKUP_ENCRYPTION_SALT:-}" ]; then
    RCLONE_CONFIG_OFFSITECRYPT_PASSWORD2=$(printf '%s' "$BACKUP_ENCRYPTION_SALT" | rclone obscure -) || return 1
    export RCLONE_CONFIG_OFFSITECRYPT_PASSWORD2
  fi
}

prune_archive() {
  cutoff=$(stamp_days_ago "$RETENTION")
  # shellcheck disable=SC2086
  rclone lsf --dirs-only offsitecrypt:uploads/archive 2>/dev/null | tr -d '/' | while IFS= read -r d; do
    case "$d" in [0-9]*-[0-9]*) ;; *) continue ;; esac
    if stamp_before "$d" "$cutoff"; then
      rclone purge "offsitecrypt:uploads/archive/$d" && log "retención: borrado uploads/archive/$d"
    fi
  done
}

run_once() {
  mkdir -p "$STATE_DIR"
  ts=$(date +%Y%m%d-%H%M%S)
  setup_crypt || { touch "$STATE_DIR/last-failure"; heartbeat "${BACKUP_OFFSITE_HEARTBEAT_URL:-}" fail "configuración incompleta"; return 1; }
  heartbeat "${BACKUP_OFFSITE_HEARTBEAT_URL:-}" start
  log "copiando a offsite:${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-patitasfind} (cifrado)"
  status=0
  if [ -d "$DB_SRC" ]; then
    # shellcheck disable=SC2086
    rclone copy "$DB_SRC" offsitecrypt:db --exclude '*.partial' --max-age 72h $RCLONE_FLAGS || status=1
    # shellcheck disable=SC2086
    rclone delete offsitecrypt:db --min-age "${RETENTION}d" $RCLONE_FLAGS || status=1
  else
    warn "no existe $DB_SRC (¿ya corrió backup.sh?)"
  fi
  if [ -d "$UPLOADS_SRC" ]; then
    # shellcheck disable=SC2086
    rclone sync "$UPLOADS_SRC" offsitecrypt:uploads/current --backup-dir "offsitecrypt:uploads/archive/$ts" \
      --exclude '.pre-restore-*/**' --exclude '.write-test' --exclude '.restore-test' $RCLONE_FLAGS || status=1
    prune_archive || status=1
  fi
  if [ "$status" -eq 0 ]; then
    touch "$STATE_DIR/last-success"
    log "listo"
    heartbeat "${BACKUP_OFFSITE_HEARTBEAT_URL:-}" ok "copia externa $ts correcta"
  else
    touch "$STATE_DIR/last-failure"
    warn "ERROR en la copia externa $ts"
    heartbeat "${BACKUP_OFFSITE_HEARTBEAT_URL:-}" fail "copia externa $ts falló (ver: docker compose logs backup-offsite)"
  fi
  return "$status"
}

health() {
  enabled || { echo "inactivo (BACKUP_S3_BUCKET vacío)"; exit 0; }
  age=$(file_age "$STATE_DIR/loop-heartbeat") || { echo "el ciclo no ha arrancado"; exit 1; }
  [ "$age" -le 7800 ] || { echo "el ciclo no avanza"; exit 1; }
  # shellcheck disable=SC3013  # -nt: lo soportan dash y busybox
  if [ -f "$STATE_DIR/last-failure" ] && { [ ! -f "$STATE_DIR/last-success" ] \
      || [ "$STATE_DIR/last-failure" -nt "$STATE_DIR/last-success" ]; }; then
    echo "la última copia externa falló"
    exit 1
  fi
  echo "ok"
  exit 0
}

case "${1:-loop}" in
  rclone)
    # Uso manual: backup-offsite.sh rclone <args>, con offsitecrypt: ya configurado
    shift
    setup_crypt || exit 1
    exec rclone "$@"
    ;;
  health) health ;;
  once) enabled && run_once ;;
  loop)
    if ! enabled; then
      loud_warning \
        "Copia externa DESACTIVADA: BACKUP_S3_BUCKET está vacío." \
        "Los respaldos solo existen en este servidor. Configura BACKUP_S3_* (Cloudflare R2/S3)."
      exec sleep infinity
    fi
    mkdir -p "$STATE_DIR"
    log "copia externa diaria desde las ${OFFSITE_HOUR:-(cada ${INTERVAL}s)} h, retención ${RETENTION} días"
    sleep "${BACKUP_OFFSITE_START_DELAY_SECONDS:-600}"   # da tiempo a que termine el respaldo local del arranque
    while :; do
      touch "$STATE_DIR/loop-heartbeat"
      if is_due "$STATE_DIR/last-success" "$OFFSITE_HOUR" "$INTERVAL"; then
        run_once || true
      fi
      sleep 3600
    done
    ;;
  *)
    echo "Uso: backup-offsite.sh [loop|once|health|rclone <args>]" >&2
    exit 2
    ;;
esac
