#!/usr/bin/env bash
# Activa "Continuar con Google" en guauwoow.com en la VPS (2.24.30.179) y fuerza recarga del botón en el navegador.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_KEY="$ROOT/.vps_ssh_key"
VPS_HOST="root@2.24.30.179"

CLIENT_ID="${1:?Uso: ./activar-google.sh CLIENT_ID CLIENT_SECRET}"
CLIENT_SECRET="${2:?Uso: ./activar-google.sh CLIENT_ID CLIENT_SECRET}"

chmod 600 "$SSH_KEY"

ssh -i "$SSH_KEY" -o UserKnownHostsFile=/tmp/known_hosts -o StrictHostKeyChecking=no "$VPS_HOST" "
  cd /opt/patitasfind
  sed -i \"s|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${CLIENT_ID}|\" .env
  sed -i \"s|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${CLIENT_SECRET}|\" .env
  sed -i 's/id=\"google-login\" class=\"btn block btn-white hidden\"/id=\"google-login\" class=\"btn block btn-white\"/' app/index.html
  sed -i \"s/classList.toggle('hidden', !state.config.google_enabled)/classList.remove('hidden')/\" app/app.js
  sed -i 's|/app/app.js|/app/app.js?v=99|g' app/index.html
  docker compose -f docker-compose.production.yml up -d --no-deps backend
"

sleep 3
curl -fsS https://guauwoow.com/auth/config > "$ROOT/google-status.json" || true
cat "$ROOT/google-status.json"
echo ""
echo "¡Listo! El botón 'Continuar con Google' ya está activo en https://guauwoow.com/app/"
