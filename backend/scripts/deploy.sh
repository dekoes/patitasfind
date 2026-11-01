#!/usr/bin/env bash
# Despliegue de GuauWoow en producción con interrupción mínima (rolling update del backend).
#
# Uso (en el servidor, desde cualquier carpeta):
#   ./backend/scripts/deploy.sh [opciones]
#
#   --pull                      git fetch + checkout de DEPLOY_BRANCH (main) + git pull --ff-only
#   --replicas N                réplicas del backend al terminar (por defecto BACKEND_REPLICAS o 1)
#   --no-build                  no construye: usa patitasfind-backend:latest
#   --tag TAG                   usa la imagen patitasfind-backend:TAG ya construida (lo usa rollback.sh)
#   --skip-migrations           no corre migraciones (rollback.sh; la base puede ir adelantada)
#   --skip-backup               no hace el dump cifrado previo a las migraciones
#   --skip-legal-check          no revisa los datos legales (solo rollback.sh)
#   --allow-legal-placeholders  despliega aunque los documentos legales tengan datos de ejemplo
#   --with-infra                recrea también PostgreSQL y Redis si cambió su configuración (corte breve)
#   Variables: DEPLOY_ENV_FILE (.env), DEPLOY_BRANCH (main), BACKEND_REPLICAS (1),
#              DEPLOY_HEALTH_TIMEOUT (240 s), DEPLOY_KEEP_IMAGES (5)
#
# Pasos:
#   1. Revisa .env, la configuración de compose y los datos legales (scripts/render-legal.py --check)
#   2. Construye patitasfind-backend:<sha del commit> (+ latest) y la imagen del respaldo
#   3. Asegura PostgreSQL/Redis, hace un dump cifrado y corre las migraciones UNA vez; sincroniza el
#      registro de versiones legales (sync-legal-docs) y cifra los documentos privados en claro
#   4. Rolling update: levanta las réplicas nuevas junto a las viejas, espera a que estén sanas,
#      recarga Nginx, apaga las viejas con calma (las peticiones en curso terminan)
#   5. Recrea Celery worker/beat y los servicios auxiliares; recarga Nginx (plantillas nuevas)
#   6. Registra la versión en .deploy/ (rollback.sh la usa) y limpia imágenes viejas
set -euo pipefail

# DEPLOY_ROOT: rollback.sh corre una copia de este script fuera del repositorio
ROOT=${DEPLOY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
cd "$ROOT"

COMPOSE_FILE_PROD=${COMPOSE_FILE_PROD:-docker-compose.production.yml}
ENV_FILE=${DEPLOY_ENV_FILE:-.env}
COMPOSE=(docker compose --project-directory "$ROOT" -f "$COMPOSE_FILE_PROD" --env-file "$ENV_FILE")
STATE_DIR="$ROOT/.deploy"
IMAGE=patitasfind-backend
HEALTH_TIMEOUT=${DEPLOY_HEALTH_TIMEOUT:-240}
KEEP_IMAGES=${DEPLOY_KEEP_IMAGES:-5}
APP_UID=1000

PULL=false
BUILD=true
TAG=""
REPLICAS=${BACKEND_REPLICAS:-1}
MIGRATE=true
PRE_BACKUP=true
LEGAL_CHECK=true
ALLOW_LEGAL=false
WITH_INFRA=false

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy] AVISO:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[deploy] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --pull) PULL=true ;;
    --replicas) REPLICAS=${2:?--replicas necesita un número}; shift ;;
    --no-build) BUILD=false ;;
    --tag) TAG=${2:?--tag necesita una etiqueta}; BUILD=false; shift ;;
    --skip-migrations) MIGRATE=false ;;
    --skip-backup) PRE_BACKUP=false ;;
    --skip-legal-check) LEGAL_CHECK=false ;;
    --allow-legal-placeholders) ALLOW_LEGAL=true ;;
    --with-infra) WITH_INFRA=true ;;
    -h | --help) usage; exit 0 ;;
    *) die "opción desconocida: $1 (usa --help)" ;;
  esac
  shift
done
[[ "$REPLICAS" =~ ^[1-9][0-9]*$ ]] || die "--replicas debe ser un número >= 1"

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || die "ya hay otro despliegue en curso"
fi

# ------------------------------------------------------------------ 1. revisiones
[ -f "$ENV_FILE" ] || die "no existe $ENV_FILE (cp .env.example .env y complétalo)"

if $PULL; then
  branch=${DEPLOY_BRANCH:-main}
  log "actualizando el código (git pull de $branch)"
  git fetch --prune
  git checkout "$branch"
  git pull --ff-only
fi

GIT_SHA=$(git rev-parse --short=12 HEAD 2>/dev/null || echo "sin-git")
if [ -n "$(git status --porcelain --untracked-files=no -- . ':(exclude).deploy' 2>/dev/null)" ]; then
  warn "hay cambios sin commit en el servidor; la imagen se marca como $GIT_SHA-dirty"
  GIT_SHA="$GIT_SHA-dirty"
fi
if [ -z "$TAG" ]; then
  TAG=$($BUILD && echo "$GIT_SHA" || echo latest)
fi
export BACKEND_TAG="$TAG" GIT_SHA

if $LEGAL_CHECK; then
  log "revisando los datos legales (scripts/render-legal.py --check)"
  legal_ok=true
  if [ ! -f scripts/render-legal.py ]; then
    warn "no existe scripts/render-legal.py"
    legal_ok=false
  elif ! command -v python3 >/dev/null 2>&1; then
    warn "no hay python3 en el servidor para revisar los datos legales"
    legal_ok=false
  elif ! python3 scripts/render-legal.py --check; then
    legal_ok=false
  fi
  if ! $legal_ok; then
    if $ALLOW_LEGAL; then
      printf '\033[1;41;37m%s\033[0m\n' \
        "################################################################################" \
        "##  ATENCIÓN: SE DESPLIEGA CON DATOS LEGALES DE EJEMPLO (--allow-legal-placeholders)" \
        "##  El aviso de privacidad y los términos NO tienen la razón social, RFC, domicilio" \
        "##  ni correos reales. Publicarlos así incumple la LFPDPPP y la LFPC." \
        "##  Completa app/legal/datos-legales.json y vuelve a desplegar." \
        "################################################################################"
      sleep 5
    else
      die "los documentos legales tienen datos pendientes. Completa app/legal/datos-legales.json y corre python3 scripts/render-legal.py (o usa --allow-legal-placeholders bajo tu responsabilidad)."
    fi
  fi
fi

log "validando $COMPOSE_FILE_PROD y .env"
config_json=$("${COMPOSE[@]}" config --format json) || die "la configuración de compose no es válida (revisa .env)"
real_ip=$(printf '%s' "$config_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["nginx"]["environment"].get("NGINX_REAL_IP",""))' 2>/dev/null || echo none)
case "$real_ip" in
  none | cloudflare) ;;
  *) die "NGINX_REAL_IP=$real_ip no es válido (usa none o cloudflare)" ;;
esac

# Carpetas del host; el backend corre como uid $APP_UID y escribe en backend/uploads
# (en Linux hace falta el dueño correcto; Docker Desktop en macOS/Windows mapea los permisos solo)
mkdir -p backend/uploads/private backups certbot/conf certbot/www
if [ "$(uname -s)" = Linux ] && [ -n "$(find backend/uploads ! -uid "$APP_UID" -print -quit 2>/dev/null)" ]; then
  log "ajustando dueño de backend/uploads a $APP_UID:$APP_UID"
  chown -R "$APP_UID:$APP_UID" backend/uploads 2>/dev/null || sudo chown -R "$APP_UID:$APP_UID" backend/uploads \
    || die "no se pudo hacer chown de backend/uploads (corre: sudo chown -R $APP_UID:$APP_UID backend/uploads)"
fi

# ------------------------------------------------------------------ 2. imágenes
if $BUILD; then
  log "construyendo $IMAGE:$TAG"
  "${COMPOSE[@]}" build backend backup
else
  docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1 || die "no existe la imagen $IMAGE:$TAG (docker image ls $IMAGE)"
  docker image inspect patitasfind-backup:16.15 >/dev/null 2>&1 || "${COMPOSE[@]}" build backup
fi

# ------------------------------------------------------------------ 3. base de datos
log "asegurando PostgreSQL y Redis"
if $WITH_INFRA; then
  warn "--with-infra: PostgreSQL/Redis se recrean si cambió su configuración (corte de unos segundos)"
  "${COMPOSE[@]}" up -d --wait postgres redis
else
  "${COMPOSE[@]}" up -d --no-recreate --wait postgres redis
fi

if $MIGRATE; then
  if $PRE_BACKUP; then
    log "dump cifrado previo a las migraciones (backups/db/)"
    "${COMPOSE[@]}" run --rm --no-deps -e BACKUP_ADHOC=1 --entrypoint sh backup /scripts/backup.sh db \
      || die "falló el dump previo; no se migró nada (usa --skip-backup si sabes lo que haces)"
  fi
  log "migraciones (una sola vez)"
  "${COMPOSE[@]}" run --rm --no-deps -e RUN_MIGRATIONS=false backend python -m app.migrate \
    || die "fallaron las migraciones; los contenedores actuales siguen corriendo sin cambios"
  # Registro de versiones legales (K-DOCS) desde backend/app/data/versiones-legales.json de la imagen nueva:
  # las aceptaciones y los avisos de 30 días usan esta tabla (el backend también la sincroniza al arrancar)
  log "registro de versiones de los documentos legales (sync-legal-docs)"
  "${COMPOSE[@]}" run --rm --no-deps -e RUN_MIGRATIONS=false backend python -m app.cli sync-legal-docs \
    || die "falló sync-legal-docs (revisa backend/app/data/versiones-legales.json: python3 scripts/render-legal.py)"
  # Cifra los documentos privados y datos fiscales que sigan en claro y pasa a la carpeta privada los documentos
  # antiguos de refugios que seguían en /uploads/ público (idempotente; los nuevos ya se cifran al guardarse).
  # Si falla, el despliegue se detiene: los contenedores actuales siguen corriendo y hay que corregirlo antes.
  log "cifrado en reposo de documentos privados en claro (encrypt-private-files)"
  "${COMPOSE[@]}" run --rm --no-deps -e RUN_MIGRATIONS=false backend python -m app.cli encrypt-private-files \
    || die "falló encrypt-private-files; revisa PRIVATE_FILES_KEY y los errores de arriba (python -m app.cli encrypt-private-files --dry-run)"
fi

# ------------------------------------------------------------------ 4. rolling update del backend
container_health() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || echo missing
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) id status
  for id in "$@"; do
    while :; do
      status=$(container_health "$id")
      case "$status" in
        healthy) break ;;
        unhealthy | exited | dead | missing) return 1 ;;
      esac
      [ "$SECONDS" -lt "$deadline" ] || return 1
      sleep 3
    done
  done
}

reload_nginx() {
  if [ -n "$("${COMPOSE[@]}" ps -q nginx 2>/dev/null)" ]; then
    # Regenera conf.d desde las plantillas (por si cambiaron) y recarga sin cortar conexiones
    "${COMPOSE[@]}" exec -T nginx sh -c \
      '/docker-entrypoint.d/20-envsubst-on-templates.sh >/dev/null && nginx -t -q && nginx -s reload' \
      || die "Nginx rechazó la configuración nueva (sigue con la anterior): revisa nginx/"
  fi
}

# Contenedores detenidos del backend (p. ej. una réplica caída): se quitan para que el escalado cree
# réplicas nuevas en lugar de reiniciar una vieja
stale=$("${COMPOSE[@]}" ps -a -q --status exited --status dead --status created backend 2>/dev/null || true)
# shellcheck disable=SC2086
[ -z "$stale" ] || docker rm -f $stale >/dev/null

old_ids=$("${COMPOSE[@]}" ps -q backend || true)
old_image=""
if [ -n "$old_ids" ]; then
  first_old=$(echo "$old_ids" | head -1)
  old_image=$(docker inspect -f '{{.Config.Image}}' "$first_old" 2>/dev/null || true)
  n_old=$(echo "$old_ids" | wc -l | tr -d ' ')
  log "rolling update: $n_old réplica(s) actual(es) ($old_image) -> $REPLICAS nueva(s) ($IMAGE:$TAG)"
  "${COMPOSE[@]}" up -d --no-deps --no-recreate --scale "backend=$((n_old + REPLICAS))" backend
  all_ids=$("${COMPOSE[@]}" ps -q backend)
  new_ids=$(comm -13 <(echo "$old_ids" | sort) <(echo "$all_ids" | sort))
  [ -n "$new_ids" ] || die "no se crearon réplicas nuevas"
  log "esperando a que las réplicas nuevas estén sanas (hasta ${HEALTH_TIMEOUT}s)"
  # shellcheck disable=SC2086
  if ! wait_healthy $new_ids; then
    warn "las réplicas nuevas no quedaron sanas; se quitan y las actuales siguen atendiendo"
    for id in $new_ids; do docker logs --tail 40 "$id" 2>&1 | sed 's/^/    /' >&2 || true; done
    # shellcheck disable=SC2086
    docker rm -f $new_ids >/dev/null
    die "despliegue cancelado (la versión anterior sigue activa)"
  fi
  reload_nginx
  sleep 3   # Nginx ya reparte entre viejas y nuevas
  log "apagando las réplicas anteriores (terminan sus peticiones en curso)"
  # shellcheck disable=SC2086
  docker stop -t 30 $old_ids >/dev/null
  reload_nginx   # de inmediato: deja de intentar las IPs que acaban de desaparecer
  # shellcheck disable=SC2086
  docker rm $old_ids >/dev/null
else
  log "primer arranque del backend ($REPLICAS réplica(s))"
  "${COMPOSE[@]}" up -d --no-deps --scale "backend=$REPLICAS" backend
  # shellcheck disable=SC2046
  wait_healthy $("${COMPOSE[@]}" ps -q backend) || die "el backend no quedó sano: ${COMPOSE[*]} logs backend"
fi

# ------------------------------------------------------------------ 5. Celery y servicios auxiliares
log "recreando Celery (el worker termina sus tareas en curso)"
"${COMPOSE[@]}" up -d --no-deps celery-worker celery-beat
log "servicios auxiliares (Nginx, certbot, respaldos)"
"${COMPOSE[@]}" up -d --no-deps nginx certbot backup backup-offsite
reload_nginx

# ------------------------------------------------------------------ 6. registro y limpieza
# "latest" apunta a lo desplegado solo cuando todo salió bien (comandos manuales de compose)
[ "$TAG" = latest ] || docker tag "$IMAGE:$TAG" "$IMAGE:latest"
{ [ -f "$STATE_DIR/current" ] && cp "$STATE_DIR/current" "$STATE_DIR/previous"; } || true
if [ -n "$old_image" ] && [ "${old_image##*:}" != "$TAG" ] && [ "${old_image##*:}" != latest ]; then
  echo "${old_image##*:}" > "$STATE_DIR/previous"
fi
echo "$TAG" > "$STATE_DIR/current"
echo "$(date -Iseconds) $TAG $(git log -1 --format=%s 2>/dev/null | cut -c1-80)" >> "$STATE_DIR/history"

# Conserva las últimas KEEP_IMAGES etiquetas (para rollback) y borra las demás si nadie las usa
mapfile -t tags < <(docker image ls "$IMAGE" --format '{{.Tag}}' | grep -vx -e latest -e "$TAG" -e '<none>' || true)
if [ "${#tags[@]}" -gt "$KEEP_IMAGES" ]; then
  for t in "${tags[@]:$KEEP_IMAGES}"; do
    if docker image rm "$IMAGE:$t" >/dev/null 2>&1; then log "imagen vieja borrada: $IMAGE:$t"; fi
  done
fi
docker image prune -f >/dev/null 2>&1 || true

# Prueba de humo a través de Nginx (no detiene el despliegue): /health debe responder 200
domain=$(printf '%s' "$config_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["nginx"]["environment"]["DOMAIN"])' 2>/dev/null || true)
if [ -n "$domain" ] && command -v curl >/dev/null 2>&1; then
  probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || true; }
  if [ "$(probe --resolve "$domain:443:127.0.0.1" "https://$domain/health")" = 200 ]; then
    log "prueba de humo: https://$domain/health responde 200"
  elif [ "$(probe -k --resolve "$domain:443:127.0.0.1" "https://$domain/health")" = 200 ]; then
    warn "https://$domain/health responde, pero el certificado no es válido para $domain"
  elif [ "$(probe -H "Host: $domain" "http://127.0.0.1/health")" = 200 ]; then
    log "prueba de humo: http://$domain/health responde 200 (modo http-only)"
  else
    warn "no se pudo comprobar /health a través de Nginx (revisa: ${COMPOSE[*]} logs nginx backend)"
  fi
fi

"${COMPOSE[@]}" ps
previous=$(cat "$STATE_DIR/previous" 2>/dev/null || echo ninguna)
log "listo: backend $IMAGE:$TAG, anterior: $previous. Reversa: ./backend/scripts/rollback.sh"
