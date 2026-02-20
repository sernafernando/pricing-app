#!/bin/bash
# Deploy script - Pricing App Frontend
# Uso: ./deploy.sh [--skip-pull] [--skip-build] [--skip-backend]

set -e

PROJECT_DIR="/var/www/html/pricing-app"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKEND_DIR="$PROJECT_DIR/backend"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

SKIP_PULL=false
SKIP_BUILD=false
SKIP_BACKEND=false

for arg in "$@"; do
  case $arg in
    --skip-pull) SKIP_PULL=true ;;
    --skip-build) SKIP_BUILD=true ;;
    --skip-backend) SKIP_BACKEND=true ;;
    *) warn "Argumento desconocido: $arg" ;;
  esac
done

cd "$PROJECT_DIR"

# 1) Git pull
if [ "$SKIP_PULL" = false ]; then
  log "Pulling latest changes..."
  git pull origin develop
else
  warn "Skipping git pull"
fi

# 2) Backend dependencies
if [ "$SKIP_BACKEND" = false ]; then
  if [ -f "$BACKEND_DIR/requirements.txt" ]; then
    log "Instalando dependencias backend..."
    source "$BACKEND_DIR/venv/bin/activate"
    pip install -q -r "$BACKEND_DIR/requirements.txt"
    deactivate
  fi
else
  warn "Skipping backend"
fi

# 3) Frontend build
if [ "$SKIP_BUILD" = false ]; then
  log "Instalando dependencias frontend..."
  cd "$FRONTEND_DIR"
  npm install --silent

  log "Building frontend..."
  npm run build
else
  warn "Skipping frontend build"
fi

# 4) Copiar sounds a dist (no están en git)
if [ -d "$FRONTEND_DIR/public/sounds" ]; then
  log "Copiando sounds a dist..."
  cp -r "$FRONTEND_DIR/public/sounds/" "$FRONTEND_DIR/dist/sounds/"
  SOUND_COUNT=$(ls "$FRONTEND_DIR/dist/sounds/"*.mp3 2>/dev/null | wc -l)
  log "  $SOUND_COUNT archivos de audio copiados"
else
  warn "No existe public/sounds/ — el pistoleado no va a tener audio"
fi

# 5) Restart backend
if [ "$SKIP_BACKEND" = false ]; then
  log "Reiniciando backend..."
  sudo systemctl restart pricing-api 2>/dev/null || warn "No se pudo reiniciar el servicio (¿existe pricing-api.service?)"
fi

log "Deploy completado"
