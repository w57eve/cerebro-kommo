#!/usr/bin/env bash
# Sube esta carpeta a un repo de GitHub (Mac/Linux).
# 1) Creá un repo VACÍO en https://github.com/new y copiá su URL .git
# 2) Ejecutá:  bash subir_a_github.sh
set -e
cd "$(dirname "$0")"
read -rp "Pegá la URL del repo de GitHub (.git): " REPO
[ -z "$REPO" ] && echo "Sin URL, cancelo." && exit 1
git init
git add .
git commit -m "Cerebro de ventas Shopping Asia - version inicial"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"
git push -u origin main
echo "Listo. Ahora en Render conectá este repo."
