# Funciones comunes de los scripts de respaldo y monitoreo de GuauWoow.
# Se carga con:  . "$(dirname "$0")/lib-backup.sh"
# POSIX sh: funciona con busybox (imágenes alpine de postgres y rclone) y con dash/bash (Debian).

# Cifrado local de los dumps (restore.sh usa los mismos parámetros para descifrar).
# shellcheck disable=SC2034  # lo usan los scripts que cargan este archivo
OPENSSL_ENC_ARGS="-aes-256-cbc -md sha256 -pbkdf2 -iter 100000 -salt"

log() {
  echo "[${LOG_TAG:-respaldo}] $(date '+%Y-%m-%dT%H:%M:%S%z') $*"
}

warn() {
  log "$*" >&2
}

# Bloque de advertencia muy visible en los logs
loud_warning() {
  {
    echo "################################################################################"
    for line in "$@"; do echo "##  $line"; done
    echo "################################################################################"
  } >&2
}

# ping_url URL [cuerpo]: GET (o POST con cuerpo) con 3 intentos. Nunca falla: solo registra el error.
ping_url() {
  _url=$1
  _body=${2:-}
  [ -n "$_url" ] || return 0
  _try=1
  while [ "$_try" -le 3 ]; do
    if command -v wget >/dev/null 2>&1; then
      if [ -n "$_body" ]; then
        wget -q -T 10 -O /dev/null --post-data="$_body" "$_url" 2>/dev/null && return 0
      else
        wget -q -T 10 -O /dev/null "$_url" 2>/dev/null && return 0
      fi
    elif command -v curl >/dev/null 2>&1; then
      if [ -n "$_body" ]; then
        curl -fsS -m 10 -o /dev/null --data-raw "$_body" "$_url" 2>/dev/null && return 0
      else
        curl -fsS -m 10 -o /dev/null "$_url" 2>/dev/null && return 0
      fi
    elif command -v python3 >/dev/null 2>&1; then
      python3 - "$_url" "$_body" <<'PY' 2>/dev/null && return 0
import sys, urllib.request
body = sys.argv[2].encode() if sys.argv[2] else None
urllib.request.urlopen(urllib.request.Request(sys.argv[1], data=body), timeout=10).read()
PY
    else
      warn "no hay wget, curl ni python3 para avisar a $_url"
      return 0
    fi
    _try=$((_try + 1))
    sleep 2
  done
  warn "no se pudo avisar a $_url (se reintentará en la siguiente corrida)"
  return 0
}

# heartbeat URL ok|start|fail [mensaje]: aviso estilo healthchecks.io
#   ok -> URL, start -> URL/start (mide la duración), fail -> URL/fail
heartbeat() {
  _base=${1%/}
  [ -n "$_base" ] || return 0
  case "$2" in
    start) ping_url "$_base/start" ;;
    fail) ping_url "$_base/fail" "${3:-}" ;;
    *) ping_url "$_base" "${3:-}" ;;
  esac
}

# Segundos desde la última modificación del archivo (falla si no existe)
file_age() {
  [ -e "$1" ] || return 1
  echo $(( $(date +%s) - $(stat -c %Y "$1") ))
}

# is_due <archivo-marca> <hora-o-vacío> <intervalo-segundos>
# Verdadero si toca correr:
#   - nunca ha corrido con éxito (no existe la marca), o
#   - la última corrida exitosa tiene más de intervalo + 2 h (se atrasó: corre ya), o
#   - con hora (0-23, zona TZ): hoy ya es esa hora o más tarde y la última corrida exitosa no fue hoy;
#   - sin hora: pasaron al menos intervalo - 10 min desde la última corrida exitosa.
is_due() {
  _stamp=$1
  _hour=$2
  _interval=$3
  [ -f "$_stamp" ] || return 0
  _age=$(file_age "$_stamp") || return 0
  [ "$_age" -ge $((_interval + 7200)) ] && return 0
  if [ -n "$_hour" ]; then
    [ "$(date -r "$_stamp" +%Y%m%d)" = "$(date +%Y%m%d)" ] && return 1
    [ "$(date +%H)" -ge "$_hour" ] && return 0
    return 1
  fi
  [ "$_age" -ge $((_interval - 600)) ]
}

# Fecha (formato AAAAMMDD-HHMMSS) de hace N días; para comparar con los nombres de los respaldos
stamp_days_ago() {
  date -d "@$(( $(date +%s) - $1 * 86400 ))" +%Y%m%d-%H%M%S
}

# stamp_before A B: verdadero si la marca A (AAAAMMDD-HHMMSS) es anterior a B (se comparan como números)
stamp_before() {
  [ "$(printf '%s' "$1" | tr -d '-')" -lt "$(printf '%s' "$2" | tr -d '-')" ]
}

# Nombres (sin ruta) de las entradas de una carpeta que cumplen la expresión regular
list_names() {
  find "$1" -mindepth 1 -maxdepth 1 2>/dev/null | sed 's#.*/##' | grep -E "$2"
}
