#!/usr/bin/env bash
set -euo pipefail

# Construye las imágenes Docker para el sandbox de ejecución (run_code)
# Debes ejecutarlo desde la raíz del proyecto o cualquier sitio:
#   ./scripts/setup.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Construyendo imagen Python..."
docker build -f sandbox/docker/Dockerfile.python -t jarvis-python:latest .

echo "Construyendo imagen Node..."
docker build -f sandbox/docker/Dockerfile.node -t jarvis-node:latest .

echo "OK: imágenes creadas:"
echo " - jarvis-python:latest"
echo " - jarvis-node:latest"