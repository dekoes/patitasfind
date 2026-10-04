#!/bin/sh
# Copia ./backups a un bucket S3/R2 con rclone (remote "offsite" configurado por variables
# RCLONE_CONFIG_OFFSITE_*). Inactivo si BACKUP_S3_BUCKET está vacío.
# La retención remota se maneja con una regla de ciclo de vida del bucket (p. ej. 30 días).
set -u
if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  echo "[offsite] BACKUP_S3_BUCKET vacío: copia externa desactivada."
  exec sleep infinity
fi
if [ -z "${RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID:-}" ] || [ -z "${RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY:-}" ]; then
  echo "[offsite] Faltan BACKUP_S3_ACCESS_KEY_ID / BACKUP_S3_SECRET_ACCESS_KEY." >&2
  exec sleep infinity
fi
DEST="offsite:${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-patitasfind}"
sleep 600  # da tiempo a que termine el respaldo local del arranque
while :; do
  echo "[offsite] $(date -Iseconds) copiando a $DEST"
  rclone copy /backups "$DEST" --exclude '*.partial' --max-age 72h --transfers 2 --log-level NOTICE \
    && echo "[offsite] listo" || echo "[offsite] ERROR en la copia" >&2
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
