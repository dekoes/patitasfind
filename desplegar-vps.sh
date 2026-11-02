#!/usr/bin/env bash
# Despliegue en un solo comando hacia la VPS de Hostinger (2.24.30.179 - guauwoow.com), desde tu computadora.
#
# Uso:   ./desplegar-vps.sh
#   GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... ./desplegar-vps.sh   (opcional: actualiza Google OAuth en el .env
#                                                                       del servidor; sin ellas no se toca)
#   ALLOW_LEGAL_PLACEHOLDERS=1 ./desplegar-vps.sh                      (solo si decides publicar con los textos
#                                                                       legales todavía incompletos: queda registrado)
#
# Qué hace, y qué protege:
#   1. Empaqueta el código del commit actual. NUNCA sube: .env (el del servidor es el de producción), la llave SSH,
#      respaldos, certificados, fotos subidas, .deploy (historial de versiones para rollback) ni node_modules.
#   2. Lo sube a una carpeta de espera en el servidor. Si se corta la conexión aquí, la versión en línea no cambia.
#   3. Copia la carpeta de espera sobre /opt/patitasfind en un solo paso local del servidor (segundos, no lo que
#      tarde tu internet en subirlo).
#   4. Corre backend/scripts/deploy.sh SEPARADO de tu sesión SSH (setsid + nohup): si cierras la laptop o se cae el
#      internet, el despliegue termina igual. Con respaldo cifrado de la base ANTES de las migraciones.
#   5. Pasa el commit (DEPLOY_GIT_SHA) para que cada versión tenga su imagen y rollback.sh pueda regresar.
#   6. Espera el resultado y revisa https://guauwoow.com/health.
# Si algo falla: ssh al servidor y  cat /opt/patitasfind/.deploy/ultimo-despliegue.log
# Para regresar a la versión anterior:  ssh ... '/opt/patitasfind/backend/scripts/rollback.sh'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SSH_KEY="$ROOT/.vps_ssh_key"
VPS_HOST="root@2.24.30.179"
REMOTE_DIR="/opt/patitasfind"
DOMAIN="guauwoow.com"

[ -f "$SSH_KEY" ] || { echo "Error: no se encontró la llave SSH en $SSH_KEY"; exit 1; }
chmod 600 "$SSH_KEY"
SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 "$VPS_HOST")

# Versión que se despliega (para la imagen y para rollback.sh)
SHA=$(git rev-parse --short=12 HEAD 2>/dev/null || echo "sin-git-$(date +%Y%m%d%H%M%S)")
if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  echo "AVISO: tienes cambios sin commit; se despliegan marcados como $SHA-local."
  echo "       Haz commit y push antes, para que GitHub tenga exactamente lo que está en línea."
  SHA="$SHA-local"
fi

DEPLOY_FLAGS=""
if [ "${ALLOW_LEGAL_PLACEHOLDERS:-}" = "1" ]; then
  echo "ATENCIÓN: publicas con textos legales incompletos (ALLOW_LEGAL_PLACEHOLDERS=1)."
  DEPLOY_FLAGS="--allow-legal-placeholders"
fi

STAGE="$REMOTE_DIR.incoming"
echo "1/4 Subiendo la versión $SHA a una carpeta de espera ($VPS_HOST:$STAGE) ..."
COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
  --exclude='._*' \
  --exclude='./.vps_ssh_key*' \
  --exclude='./.env' \
  --exclude='./.env.*' \
  --exclude='./.deploy' \
  --exclude='./backups' \
  --exclude='./certbot' \
  --exclude='./backend/uploads' \
  --exclude='./app/node_modules' \
  --exclude='./app/e2e-shots' \
  --exclude='./marketing' \
  --exclude='./mockups' \
  --exclude='./vindam2.0' \
  --exclude='./.git' \
  --exclude='__pycache__' \
  . | "${SSH[@]}" "rm -rf '$STAGE' && mkdir -p '$STAGE' && tar -xzf - -C '$STAGE' && find '$STAGE' -name '._*' -delete && touch '$STAGE/.completo'"

echo "2/4 Poniendo el código en $REMOTE_DIR ..."
"${SSH[@]}" "set -e
  test -f '$STAGE/.completo' || { echo 'La subida no terminó; no se toca la versión en línea.'; exit 1; }
  rm -f '$STAGE/.completo'
  mkdir -p '$REMOTE_DIR' && cp -a '$STAGE/.' '$REMOTE_DIR/' && rm -rf '$STAGE'
  test -f '$REMOTE_DIR/.env' || { echo 'Falta $REMOTE_DIR/.env en el servidor (cp .env.example .env y complétalo).'; exit 1; }"

if [ -n "${GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
  echo "    Actualizando Google OAuth en el .env del servidor ..."
  # Por stdin (no en la línea de comandos: no queda en el historial ni en la lista de procesos del servidor)
  printf '%s\n%s\n' "$GOOGLE_CLIENT_ID" "$GOOGLE_CLIENT_SECRET" | "${SSH[@]}" "cd '$REMOTE_DIR' && python3 -c '
import re, sys
cid, secret = sys.stdin.read().splitlines()[:2]
text = open(\".env\").read()
for key, value in ((\"GOOGLE_CLIENT_ID\", cid), (\"GOOGLE_CLIENT_SECRET\", secret)):
    line = f\"{key}={value}\"
    text = re.sub(rf\"^{key}=.*\$\", lambda m: line, text, flags=re.M) if re.search(rf\"^{key}=\", text, re.M) else text.rstrip(\"\\n\") + \"\\n\" + line + \"\\n\"
open(\".env\", \"w\").write(text)
'"
fi

echo "3/4 Desplegando (respaldo de la base, migraciones, cambio gradual del backend) ..."
"${SSH[@]}" "cd '$REMOTE_DIR' && chmod +x backend/scripts/*.sh && mkdir -p .deploy && rm -f .deploy/ultimo-despliegue.exit && : > .deploy/ultimo-despliegue.log &&
  DEPLOY_GIT_SHA='$SHA' setsid nohup bash -c './backend/scripts/deploy.sh $DEPLOY_FLAGS; echo \$? > .deploy/ultimo-despliegue.exit' \
    > .deploy/ultimo-despliegue.log 2>&1 < /dev/null &"
# Muestra el avance; si se corta la conexión, el despliegue sigue en el servidor
"${SSH[@]}" "cd '$REMOTE_DIR'; (until [ -f .deploy/ultimo-despliegue.exit ]; do sleep 2; done) & waiter=\$!
  tail -n +1 -F .deploy/ultimo-despliegue.log --pid=\$waiter 2>/dev/null; wait \$waiter
  exit \$(cat .deploy/ultimo-despliegue.exit)" || {
  echo
  echo "El despliegue FALLÓ (o se cortó la conexión mientras se mostraba). Revisa en el servidor:"
  echo "  ssh -i .vps_ssh_key $VPS_HOST 'cat $REMOTE_DIR/.deploy/ultimo-despliegue.log'"
  exit 1
}

echo "4/4 Verificando https://$DOMAIN/health ..."
for i in 1 2 3 4 5 6; do
  if curl -fsS --max-time 10 "https://$DOMAIN/health"; then echo; echo "Listo: versión $SHA en línea en https://$DOMAIN"; exit 0; fi
  sleep 5
done
echo "El servidor no responde sano en https://$DOMAIN/health. Para regresar a la versión anterior:"
echo "  ssh -i .vps_ssh_key $VPS_HOST '$REMOTE_DIR/backend/scripts/rollback.sh'"
exit 1
