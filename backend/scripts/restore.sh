#!/bin/sh
# Restaura un respaldo de PatitasFind.
#
#   docker compose -f docker-compose.production.yml stop backend celery-worker celery-beat
#   docker compose -f docker-compose.production.yml run --rm --entrypoint sh backup \
#       /scripts/restore.sh /backups/db-YYYYMMDD-HHMMSS.dump [/backups/uploads-YYYYMMDD-HHMMSS.tar.gz]
#   docker compose -f docker-compose.production.yml up -d
#
# - La base se restaura con pg_restore --clean --if-exists (reemplaza los objetos existentes).
# - Las fotos se extraen sobre /uploads (= ./backend/uploads); los archivos actuales se mueven antes
#   a /uploads/.pre-restore-<fecha> por si hay que revertir.
# Pide confirmación salvo que se pase RESTORE_YES=1.
set -eu

DUMP=${1:-}
UPLOADS_TAR=${2:-}
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
  echo "Uso: restore.sh /backups/db-<fecha>.dump [/backups/uploads-<fecha>.tar.gz]" >&2
  ls -1t /backups 2>/dev/null | head -20 >&2 || true
  exit 1
fi

echo "Se restaurará la base '${PGDATABASE}' en ${PGHOST} desde: $DUMP"
[ -n "$UPLOADS_TAR" ] && echo "y las fotos desde: $UPLOADS_TAR"
if [ "${RESTORE_YES:-0}" != "1" ]; then
  printf "Esto REEMPLAZA los datos actuales. Escribe RESTAURAR para continuar: "
  read -r answer
  [ "$answer" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
fi

pg_isready -q || { echo "PostgreSQL no responde en $PGHOST" >&2; exit 1; }
echo "[restore] restaurando base de datos..."
pg_restore --clean --if-exists --no-owner --exit-on-error -d "$PGDATABASE" "$DUMP"
echo "[restore] base restaurada."

if [ -n "$UPLOADS_TAR" ]; then
  [ -f "$UPLOADS_TAR" ] || { echo "No existe $UPLOADS_TAR" >&2; exit 1; }
  stamp=$(date +%Y%m%d-%H%M%S)
  mkdir -p "/uploads/.pre-restore-$stamp"
  find /uploads -mindepth 1 -maxdepth 1 ! -name '.pre-restore-*' -exec mv {} "/uploads/.pre-restore-$stamp/" \;
  tar -xzf "$UPLOADS_TAR" -C /uploads
  echo "[restore] fotos restauradas (las anteriores quedaron en /uploads/.pre-restore-$stamp)."
fi
echo "[restore] listo. Levanta de nuevo: docker compose -f docker-compose.production.yml up -d"
