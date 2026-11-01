#!/usr/bin/env bash
# Configura Twilio para verificación obligatoria por SMS en guauwoow.com
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "========================================================"
echo "  Configuración de Twilio SMS para GuauWoow"
echo "========================================================"
read -rp "1. Pega tu Twilio Account SID (empieza con AC...): " TWILIO_SID
read -rp "2. Pega tu Twilio Auth Token: " TWILIO_TOKEN
read -rp "3. Pega tu número de Twilio (+1...) o Messaging Service SID (MG...): " TWILIO_FROM

./activar-sms.sh twilio "$TWILIO_SID" "$TWILIO_TOKEN" "$TWILIO_FROM"
echo ""
read -n 1 -s -r -p "Presiona cualquier tecla para cerrar..."
