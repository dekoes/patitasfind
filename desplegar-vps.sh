#!/usr/bin/env bash
# Script de despliegue en un solo comando hacia la VPS de Hostinger (2.24.30.179 - guauwoow.com)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SSH_KEY="$ROOT/.vps_ssh_key"
VPS_HOST="root@2.24.30.179"
REMOTE_DIR="/opt/patitasfind"

if [ ! -f "$SSH_KEY" ]; then
  echo "Error: No se encontró la llave SSH en $SSH_KEY"
  exit 1
fi
chmod 600 "$SSH_KEY"

echo "1/3 Subiendo archivos del proyecto a $VPS_HOST:$REMOTE_DIR ..."
COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
  --exclude='._*' \
  --exclude='./.vps_ssh_key*' \
  --exclude='./app/node_modules' \
  --exclude='./app/e2e-shots' \
  --exclude='./marketing' \
  --exclude='./mockups' \
  --exclude='./vindam2.0' \
  --exclude='./.git' \
  --exclude='__pycache__' \
  . | ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$VPS_HOST" "mkdir -p $REMOTE_DIR && tar -xzf - -C $REMOTE_DIR && find $REMOTE_DIR -name '._*' -delete"

echo "2/3 Configurando Google OAuth y desplegando contenedores en la VPS..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$VPS_HOST" "
  cd $REMOTE_DIR
  sed -i 's|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:?Define GOOGLE_CLIENT_ID}|' .env
  sed -i 's|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:?Define GOOGLE_CLIENT_SECRET}|' .env
  chmod +x backend/scripts/deploy.sh
  ./backend/scripts/deploy.sh --allow-legal-placeholders --skip-backup
"

echo "3/3 Verificando estado del servidor en https://guauwoow.com/health ..."
curl -fsS https://guauwoow.com/health && echo ""
echo "¡Despliegue completado con éxito en https://guauwoow.com!"
