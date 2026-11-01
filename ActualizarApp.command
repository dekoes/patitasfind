#!/usr/bin/env bash
# Despliega la actualización de botones directos (Reportar encontrado + Dar en adopción como particular) y Google OAuth en guauwoow.com
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
./desplegar-vps.sh
echo ""
read -n 1 -s -r -p "Presiona cualquier tecla para cerrar..."
