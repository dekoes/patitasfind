#!/usr/bin/env bash
# Configura Zernio (https://zernio.com) para verificación obligatoria por SMS en guauwoow.com
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "========================================================"
echo "  Configuración de Zernio SMS para GuauWoow"
echo "========================================================"
read -rp "1. Pega tu Zernio API Key: " ZERNIO_KEY
read -rp "2. Escribe tu número de Zernio (+1... / +52...) o Sender ID de marca [por defecto: GUAUWOOW]: " ZERNIO_FROM
ZERNIO_FROM="${ZERNIO_FROM:-GUAUWOOW}"

./activar-sms.sh zernio "$ZERNIO_KEY" "$ZERNIO_FROM"
echo ""
read -n 1 -s -r -p "Presiona cualquier tecla para cerrar..."
