#!/bin/sh
# Respaldo de PatitasFind: base de datos (pg_dump -Fc) + fotos subidas (tar.gz) en /backups.
# Uso: backup.sh          -> un respaldo
#      backup.sh loop     -> respaldo ahora y luego cada BACKUP_INTERVAL_SECONDS (24 h)
# Variables: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, BACKUP_RETENTION_DAYS (14)
set -eu

BACKUP_DIR=${BACKUP_DIR:-/backups}
UPLOADS_DIR=${UPLOADS_DIR:-/uploads}
RETENTION=${BACKUP_RETENTION_DAYS:-14}
INTERVAL=${BACKUP_INTERVAL_SECONDS:-86400}

run_backup() {
  ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$BACKUP_DIR"
  echo "[backup] $(date -Iseconds) iniciando ($ts)"
  pg_dump -Fc --no-owner -f "$BACKUP_DIR/db-$ts.dump.partial"
  mv "$BACKUP_DIR/db-$ts.dump.partial" "$BACKUP_DIR/db-$ts.dump"
  if [ -d "$UPLOADS_DIR" ]; then
    tar -czf "$BACKUP_DIR/uploads-$ts.tar.gz.partial" -C "$UPLOADS_DIR" .
    mv "$BACKUP_DIR/uploads-$ts.tar.gz.partial" "$BACKUP_DIR/uploads-$ts.tar.gz"
  fi
  # Retención: borra respaldos con más de N días
  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' -o -name '*.partial' \) \
    -mtime +"$RETENTION" -print -delete
  echo "[backup] listo: $(ls -1 "$BACKUP_DIR" | wc -l) archivos en $BACKUP_DIR"
  ls -lh "$BACKUP_DIR/db-$ts.dump" "$BACKUP_DIR/uploads-$ts.tar.gz" 2>/dev/null || true
}

if [ "${1:-}" = "loop" ]; then
  sleep 30  # deja que PostgreSQL termine de arrancar
  while :; do
    run_backup || echo "[backup] ERROR: el respaldo falló" >&2
    sleep "$INTERVAL"
  done
else
  run_backup
fi
