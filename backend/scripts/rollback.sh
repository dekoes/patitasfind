#!/usr/bin/env bash
# Vuelve GuauWoow a una versión anterior (código + imagen del backend) sin migrar la base.
#
#   ./backend/scripts/rollback.sh               -> a la versión anterior (.deploy/previous)
#   ./backend/scripts/rollback.sh <tag|commit>  -> a esa versión
#   ./backend/scripts/rollback.sh --list        -> versiones desplegadas e imágenes disponibles
#   --image-only                                -> solo cambia la imagen del backend (no toca el código:
#                                                  Nginx y el frontend quedan en la versión actual)
#
# Qué hace: git checkout --detach <commit> (frontend y Nginx coherentes con el backend) y
# deploy.sh --tag <tag> --skip-migrations (rolling update, sin cortar el servicio). Si la imagen ya
# no existe, la reconstruye desde ese commit. Siempre usa el deploy.sh ACTUAL (se copia antes del
# checkout), aunque el commit de destino tenga uno más viejo.
# NO revierte migraciones: las migraciones deben ser compatibles hacia atrás (agregar columnas, no
# borrarlas en el mismo despliegue). Si una migración rompió datos, restaura el dump previo al
# despliegue (backups/db/, ver docs/operacion.md) ANTES de este script.
# Para volver a la rama principal después: ./backend/scripts/deploy.sh --pull
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
STATE_DIR="$ROOT/.deploy"
IMAGE=patitasfind-backend

log() { printf '\033[1;34m[rollback]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[rollback] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

IMAGE_ONLY=false
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --list)
      echo "Desplegadas (más recientes al final):"
      tail -n 15 "$STATE_DIR/history" 2>/dev/null || echo "  (sin historial)"
      echo "Actual: $(cat "$STATE_DIR/current" 2>/dev/null || echo '?')   Anterior: $(cat "$STATE_DIR/previous" 2>/dev/null || echo '?')"
      echo "Imágenes disponibles:"
      docker image ls "$IMAGE" --format '  {{.Tag}}\t{{.CreatedSince}}'
      exit 0
      ;;
    --image-only) IMAGE_ONLY=true ;;
    -h | --help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "opción desconocida: $arg" ;;
    *) TARGET=$arg ;;
  esac
done

if [ -z "$TARGET" ]; then
  TARGET=$(cat "$STATE_DIR/previous" 2>/dev/null || true)
  [ -n "$TARGET" ] || die "no hay versión anterior registrada; indica una: rollback.sh <tag> (ver --list)"
fi
TAG=${TARGET%-dirty}

# Copia del deploy.sh actual: tras el checkout, el del commit viejo podría no existir o ser distinto
runner=$(mktemp "${TMPDIR:-/tmp}/patitasfind-deploy.XXXXXX")
cp "$ROOT/backend/scripts/deploy.sh" "$runner"
chmod 700 "$runner"
export DEPLOY_ROOT="$ROOT"

if ! $IMAGE_ONLY; then
  [ -z "$(git status --porcelain --untracked-files=no -- . ':(exclude).deploy')" ] \
    || die "hay cambios sin commit en el servidor; guárdalos o usa --image-only"
  commit=$(git rev-parse --verify --quiet "$TAG^{commit}") || die "no existe el commit $TAG (git fetch?)"
  TAG=$(git rev-parse --short=12 "$commit")
  log "código -> $TAG ($(git log -1 --format=%s "$commit" | cut -c1-70))"
  git -c advice.detachedHead=false checkout --detach "$commit"
fi

if docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
  log "imagen $IMAGE:$TAG disponible: rolling update sin migraciones"
  exec "$runner" --tag "$TAG" --skip-migrations --skip-backup --skip-legal-check
fi
$IMAGE_ONLY && die "no existe la imagen $IMAGE:$TAG y con --image-only no se puede reconstruir"
log "la imagen $IMAGE:$TAG ya no existe: se reconstruye desde el commit"
exec "$runner" --skip-migrations --skip-backup --skip-legal-check
