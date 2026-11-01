#!/usr/bin/env bash
# Activa la verificación obligatoria de celular por SMS (REQUIRE_PHONE_VERIFICATION=true) en guauwoow.com
# Uso con Zernio:      ./activar-sms.sh zernio "TU_ZERNIO_API_KEY" "TU_NUMERO_O_SENDER_ID"
# Uso con SMS Masivos: ./activar-sms.sh smsmasivos "TU_SMSMASIVOS_API_KEY"
# Uso con Twilio:      ./activar-sms.sh twilio "AC_SID" "AUTH_TOKEN" "+1_NUMERO_O_MG_SID"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_KEY="$ROOT/.vps_ssh_key"
VPS_HOST="root@2.24.30.179"
REMOTE_DIR="/opt/patitasfind"

PROVIDER="${1:-}"
if [ -z "$PROVIDER" ]; then
  echo "Uso:"
  echo "  Zernio:      ./activar-sms.sh zernio \"TU_ZERNIO_API_KEY\" \"GUAUWOOW_O_+1234567890\""
  echo "  SMS Masivos: ./activar-sms.sh smsmasivos \"TU_API_KEY\""
  echo "  Twilio:      ./activar-sms.sh twilio \"TU_ACCOUNT_SID\" \"TU_AUTH_TOKEN\" \"+1234567890\""
  exit 1
fi

chmod 600 "$SSH_KEY"

if [ "$PROVIDER" = "zernio" ]; then
  Z_KEY="${2:?Falta tu ZERNIO_API_KEY}"
  Z_FROM="${3:-GUAUWOOW}"
  echo "1/2 Subiendo integración de Zernio y mejoras de la app a $VPS_HOST ..."
  COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
    backend/app/config.py \
    backend/app/services/sms.py \
    backend/app/routers/dogs.py \
    docker-compose.production.yml \
    docker-compose.yml \
    app/index.html \
    app/app.js \
    | ssh -i "$SSH_KEY" -o UserKnownHostsFile=/tmp/known_hosts -o StrictHostKeyChecking=no "$VPS_HOST" "tar -xzf - -C $REMOTE_DIR"

  echo "2/2 Configurando Zernio en .env y reconstruyendo el backend en la VPS..."
  ssh -i "$SSH_KEY" -o UserKnownHostsFile=/tmp/known_hosts -o StrictHostKeyChecking=no "$VPS_HOST" "
    cd $REMOTE_DIR
    grep -q '^ZERNIO_API_KEY=' .env && sed -i \"s|^ZERNIO_API_KEY=.*|ZERNIO_API_KEY=${Z_KEY}|\" .env || echo \"ZERNIO_API_KEY=${Z_KEY}\" >> .env
    grep -q '^ZERNIO_FROM=' .env && sed -i \"s|^ZERNIO_FROM=.*|ZERNIO_FROM=${Z_FROM}|\" .env || echo \"ZERNIO_FROM=${Z_FROM}\" >> .env
    sed -i 's|^SMS_PROVIDER=.*|SMS_PROVIDER=zernio|' .env
    sed -i 's|^REQUIRE_PHONE_VERIFICATION=.*|REQUIRE_PHONE_VERIFICATION=true|' .env
    sed -i 's|^GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:?Define GOOGLE_CLIENT_ID}|' .env
    sed -i 's|^GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:?Define GOOGLE_CLIENT_SECRET}|' .env
    docker compose -f docker-compose.production.yml build backend
    docker compose -f docker-compose.production.yml up -d --no-deps backend celery-worker celery-beat
  "
elif [ "$PROVIDER" = "smsmasivos" ]; then
  API_KEY="${2:?Falta la API Key de SMS Masivos}"
  ssh -i "$SSH_KEY" -o UserKnownHostsFile=/tmp/known_hosts -o StrictHostKeyChecking=no "$VPS_HOST" "
    cd $REMOTE_DIR
    grep -q '^SMSMASIVOS_API_KEY=' .env && sed -i \"s|^SMSMASIVOS_API_KEY=.*|SMSMASIVOS_API_KEY=${API_KEY}|\" .env || echo \"SMSMASIVOS_API_KEY=${API_KEY}\" >> .env
    sed -i 's|^SMS_PROVIDER=.*|SMS_PROVIDER=smsmasivos|' .env
    sed -i 's|^REQUIRE_PHONE_VERIFICATION=.*|REQUIRE_PHONE_VERIFICATION=true|' .env
    docker compose -f docker-compose.production.yml up -d --no-deps backend celery-worker
  "
elif [ "$PROVIDER" = "twilio" ]; then
  SID="${2:?Falta el Account SID de Twilio}"
  TOKEN="${3:?Falta el Auth Token de Twilio}"
  FROM="${4:?Falta el número From (+1...) o Messaging Service SID (MG...)}"
  ssh -i "$SSH_KEY" -o UserKnownHostsFile=/tmp/known_hosts -o StrictHostKeyChecking=no "$VPS_HOST" "
    cd $REMOTE_DIR
    grep -q '^TWILIO_ACCOUNT_SID=' .env && sed -i \"s|^TWILIO_ACCOUNT_SID=.*|TWILIO_ACCOUNT_SID=${SID}|\" .env || echo \"TWILIO_ACCOUNT_SID=${SID}\" >> .env
    grep -q '^TWILIO_AUTH_TOKEN=' .env && sed -i \"s|^TWILIO_AUTH_TOKEN=.*|TWILIO_AUTH_TOKEN=${TOKEN}|\" .env || echo \"TWILIO_AUTH_TOKEN=${TOKEN}\" >> .env
    if [[ \"$FROM\" == MG* ]]; then
      grep -q '^TWILIO_MESSAGING_SERVICE_SID=' .env && sed -i \"s|^TWILIO_MESSAGING_SERVICE_SID=.*|TWILIO_MESSAGING_SERVICE_SID=${FROM}|\" .env || echo \"TWILIO_MESSAGING_SERVICE_SID=${FROM}\" >> .env
    else
      grep -q '^TWILIO_FROM_NUMBER=' .env && sed -i \"s|^TWILIO_FROM_NUMBER=.*|TWILIO_FROM_NUMBER=${FROM}|\" .env || echo \"TWILIO_FROM_NUMBER=${FROM}\" >> .env
    fi
    sed -i 's|^SMS_PROVIDER=.*|SMS_PROVIDER=twilio|' .env
    sed -i 's|^REQUIRE_PHONE_VERIFICATION=.*|REQUIRE_PHONE_VERIFICATION=true|' .env
    docker compose -f docker-compose.production.yml up -d --no-deps backend celery-worker
  "
else
  echo "Proveedor no válido: usa 'zernio', 'smsmasivos' o 'twilio'"
  exit 1
fi

sleep 4
curl -fsS https://guauwoow.com/auth/config && echo ""
echo "¡Listo! La verificación obligatoria por SMS ya está activa en https://guauwoow.com/app/"
