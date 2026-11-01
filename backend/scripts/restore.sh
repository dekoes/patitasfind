#!/bin/sh
# Restaura un respaldo de GuauWoow (corre en el contenedor "backup").
#
#   F="docker compose -f docker-compose.production.yml"
#   $F stop backend celery-worker celery-beat
#   # Solo la base:
#   $F run --rm --entrypoint sh backup /scripts/restore.sh /backups/db/db-AAAAMMDD-HHMMSS.dump.enc
#   # Base + fotos (la carpeta de fotos se monta con escritura en /uploads-rw):
#   $F run --rm -v "$PWD/backend/uploads:/uploads-rw" -e UPLOADS_DIR=/uploads-rw --entrypoint sh backup \
#       /scripts/restore.sh /backups/db/db-AAAAMMDD-HHMMSS.dump.enc /backups/uploads/AAAAMMDD-HHMMSS
#   ./backend/scripts/deploy.sh --no-build      # vuelve a levantar todo (y corrige permisos de uploads)
#
# Simulacro mensual sin tocar producción (restaura en otra base y la borra):
#   $F run --rm -e PGDATABASE=patitasfind_restore_test -e RESTORE_CREATE_DB=1 -e RESTORE_YES=1 \
#       --entrypoint sh backup /scripts/restore.sh /backups/db/<último>.dump.enc
#   $F exec postgres dropdb -U patitasfind patitasfind_restore_test
#
# - .dump.enc: cifrado por backup.sh; se descifra con BACKUP_ENCRYPTION_PASSWORD (la misma del respaldo).
#   .dump: formato anterior sin cifrar.
# - La base se restaura con pg_restore --clean --if-exists en UNA transacción: si algo falla, la base
#   queda como estaba.
# - Fotos: una instantánea (carpeta /backups/uploads/<fecha>) o un uploads-*.tar.gz antiguo. Las fotos
#   actuales se mueven antes a UPLOADS_DIR/.pre-restore-<fecha> por si hay que revertir.
# Variables: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (base destino), UPLOADS_DIR (/uploads),
#   RESTORE_YES=1 (sin confirmación), RESTORE_CREATE_DB=1 (crea la base destino si no existe).
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_TAG=restore
. "$SCRIPT_DIR/lib-backup.sh"

DUMP=${1:-}
UPLOADS_SRC=${2:-}
UPLOADS_DIR=${UPLOADS_DIR:-/uploads}
BACKUP_DIR=${BACKUP_DIR:-/backups}

if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
  echo "Uso: restore.sh /backups/db/db-<fecha>.dump.enc [/backups/uploads/<fecha> | uploads-<fecha>.tar.gz]" >&2
  echo "Respaldos disponibles (más recientes primero):" >&2
  { list_names "$BACKUP_DIR/db" '^db-' | sort -r | head -10 | sed "s#^#$BACKUP_DIR/db/#"
    list_names "$BACKUP_DIR/uploads" '^[0-9]{8}-[0-9]{6}$' | sort -r | head -5 | sed "s#^#$BACKUP_DIR/uploads/#"
    list_names "$BACKUP_DIR" '^(db-.*\.dump|uploads-.*\.tar\.gz)$' | sort -r | head -5 | sed "s#^#$BACKUP_DIR/#"
  } >&2 || true
  exit 1
fi
if [ -n "$UPLOADS_SRC" ] && [ ! -e "$UPLOADS_SRC" ]; then
  echo "No existe $UPLOADS_SRC" >&2
  exit 1
fi

# Descifra (si hace falta) hacia la salida estándar
read_dump() {
  case "$DUMP" in
    *.enc)
      # shellcheck disable=SC2086
      openssl enc -d $OPENSSL_ENC_ARGS -pass env:BACKUP_ENCRYPTION_PASSWORD -in "$DUMP"
      ;;
    *) cat "$DUMP" ;;
  esac
}

case "$DUMP" in
  *.enc)
    if [ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]; then
      echo "El respaldo está cifrado: define BACKUP_ENCRYPTION_PASSWORD (la misma con la que se hizo)." >&2
      exit 1
    fi
    ;;
esac
# Antes de tocar nada: la contraseña es correcta y el archivo es un dump válido
if ! read_dump 2>/dev/null | pg_restore --list >/dev/null 2>&1; then
  echo "No se pudo leer $DUMP: contraseña incorrecta o archivo dañado. No se cambió nada." >&2
  exit 1
fi

echo "Se restaurará la base '${PGDATABASE}' en ${PGHOST:-localhost} desde: $DUMP"
[ -n "$UPLOADS_SRC" ] && echo "y las fotos en $UPLOADS_DIR desde: $UPLOADS_SRC"
if [ "${RESTORE_YES:-0}" != "1" ]; then
  printf "Esto REEMPLAZA los datos actuales. Escribe RESTAURAR para continuar: "
  read -r answer
  [ "$answer" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
fi

pg_isready -q || { echo "PostgreSQL no responde en ${PGHOST:-localhost}" >&2; exit 1; }
if [ "${RESTORE_CREATE_DB:-0}" = "1" ]; then
  if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$PGDATABASE'" | grep -q 1; then
    createdb "$PGDATABASE"
    log "base '$PGDATABASE' creada"
  fi
fi

log "restaurando base de datos..."
tmp_err=$(mktemp)
if ! read_dump | pg_restore --clean --if-exists --no-owner --single-transaction -d "$PGDATABASE" 2>"$tmp_err"; then
  cat "$tmp_err" >&2
  rm -f "$tmp_err"
  echo "[restore] ERROR: la restauración falló; la transacción se revirtió y la base quedó como estaba." >&2
  exit 1
fi
rm -f "$tmp_err"
log "base restaurada: $(psql -d "$PGDATABASE" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'") tablas."

if [ -n "$UPLOADS_SRC" ]; then
  if ! touch "$UPLOADS_DIR/.restore-test" 2>/dev/null; then
    echo "[restore] ERROR: $UPLOADS_DIR es de solo lectura. Monta la carpeta con escritura (ver el comando de arriba)." >&2
    exit 1
  fi
  rm -f "$UPLOADS_DIR/.restore-test"
  stamp=$(date +%Y%m%d-%H%M%S)
  keep="$UPLOADS_DIR/.pre-restore-$stamp"
  mkdir -p "$keep"
  find "$UPLOADS_DIR" -mindepth 1 -maxdepth 1 ! -name '.pre-restore-*' -exec mv {} "$keep/" \;
  if [ -d "$UPLOADS_SRC" ]; then
    cp -a "$UPLOADS_SRC/." "$UPLOADS_DIR/"
  else
    tar -xzf "$UPLOADS_SRC" -C "$UPLOADS_DIR"
  fi
  log "fotos restauradas: $(find "$UPLOADS_DIR" -path "$UPLOADS_DIR/.pre-restore-*" -prune -o -type f -print | wc -l | tr -d ' ') archivos (las anteriores quedaron en $keep)."
fi
log "listo. Vuelve a levantar: ./backend/scripts/deploy.sh --no-build"
