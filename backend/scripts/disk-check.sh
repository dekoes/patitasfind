#!/bin/sh
# Revisa el uso de disco y avisa si alguna ruta pasa del umbral (lo llama backup.sh loop cada hora).
#
#   disk-check.sh            -> sale con 0 si todo está bien, 1 si alguna ruta pasa el umbral
#
# Variables:
#   DISK_CHECK_PATHS      rutas a medir (por defecto "/ /backups /uploads"; en el contenedor de
#                         respaldo "/" es el disco de Docker con los volúmenes de PostgreSQL)
#   DISK_ALERT_THRESHOLD  porcentaje de uso que dispara la alerta (85)
#   DISK_ALERT_URL        aviso estilo healthchecks.io: se hace ping a la URL cuando todo está bien y a
#                         <URL>/fail (con el detalle) cuando se pasa el umbral; así la alerta también
#                         salta si el servidor deja de reportar. Vacío = solo se escribe en el log.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_TAG=disco
. "$SCRIPT_DIR/lib-backup.sh"

THRESHOLD=${DISK_ALERT_THRESHOLD:-85}
PATHS=${DISK_CHECK_PATHS:-/ /backups /uploads}

report=""
over=0
seen=""
for p in $PATHS; do
  [ -e "$p" ] || continue
  # df -P: una línea por sistema de archivos (portátil entre busybox y GNU)
  line=$(df -P "$p" 2>/dev/null | tail -1) || continue
  [ -n "$line" ] || continue
  fs=$(echo "$line" | awk '{print $1}')
  case " $seen " in *" $fs "*) continue ;; esac   # el mismo disco montado en otra ruta se mide una vez
  seen="$seen $fs"
  used=$(echo "$line" | awk '{gsub("%", "", $5); print $5}')
  avail_kb=$(echo "$line" | awk '{print $4}')
  avail_gb=$(awk "BEGIN {printf \"%.1f\", $avail_kb / 1048576}")
  report="$report $p=${used}% (libres ${avail_gb} GB);"
  if [ "$used" -ge "$THRESHOLD" ]; then
    over=1
  fi
done

if [ "$over" -eq 1 ]; then
  msg="ALERTA de disco en $(hostname): uso por encima de ${THRESHOLD}%:${report} Libera espacio (docs/operacion.md, sección Disco)."
  loud_warning "$msg"
  heartbeat "${DISK_ALERT_URL:-}" fail "$msg"
  exit 1
fi
log "uso de disco correcto:${report}"
heartbeat "${DISK_ALERT_URL:-}" ok "disco correcto:${report}"
exit 0
