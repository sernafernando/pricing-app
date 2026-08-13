#!/bin/bash
# Deploy script - Pricing App Frontend
# Uso: ./deploy.sh [--skip-pull] [--skip-build] [--skip-backend] [--no-notify]
#
# Avisa por WhatsApp (wabot) al arrancar y al terminar. El aviso es best-effort:
# nunca puede romper ni frenar el deploy.
#
# Variables de entorno opcionales:
#   DEPLOY_ETA_MIN      minutos estimados que se comunican al equipo (default 5)
#   HEALTHCHECK_URL     URL que se consulta para confirmar que el backend levantó
#   HEALTHCHECK_TIMEOUT segundos máximos de espera del health check (default 120)
#   WABOT_TOKEN         token del servicio; si falta, el helper no manda nada

# -E propaga el trap ERR a las funciones; sin eso un fallo adentro de una
# función no dispararía el aviso de deploy fallido.
set -eE

PROJECT_DIR="/var/www/html/pricing-app"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKEND_DIR="$PROJECT_DIR/backend"

NOTIFY_SCRIPT="$PROJECT_DIR/scripts/notify-wabot.sh"
DEPLOY_ETA_MIN="${DEPLOY_ETA_MIN:-5}"
# El /health se sirve por el reverse proxy. El puerto crudo del backend
# (8000) devuelve 404 en esa ruta, así que no sirve para verificar nada.
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://pricing.gaussonline.com.ar/health}"
HEALTHCHECK_TIMEOUT="${HEALTHCHECK_TIMEOUT:-120}"

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
NOTIFY=true

for arg in "$@"; do
  case $arg in
    --skip-pull) SKIP_PULL=true ;;
    --skip-build) SKIP_BUILD=true ;;
    --skip-backend) SKIP_BACKEND=true ;;
    --no-notify) NOTIFY=false ;;
    *) warn "Argumento desconocido: $arg" ;;
  esac
done

# Paso actual, para poder decir en qué se cortó si el deploy falla.
CURRENT_STEP="inicio"

# Manda un aviso por WhatsApp. El helper siempre sale 0, pero el `|| true`
# deja explícito que un fallo de notificación jamás corta el deploy.
notify() {
  [ "$NOTIFY" = true ] || return 0

  if [ ! -x "$NOTIFY_SCRIPT" ]; then
    warn "No se encontró $NOTIFY_SCRIPT — sin aviso por WhatsApp"
    return 0
  fi

  "$NOTIFY_SCRIPT" "$1" || true
}

fmt_duration() {
  printf '%dm %02ds' $(($1 / 60)) $(($1 % 60))
}

# Espera a que el backend conteste el health check. El systemctl restart
# vuelve enseguida, pero uvicorn tarda en estar listo: sin esta espera
# avisaríamos "ya está arriba" antes de que sea cierto.
wait_for_backend() {
  local deadline=$((SECONDS + HEALTHCHECK_TIMEOUT))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -sf --max-time 5 -o /dev/null "$HEALTHCHECK_URL"; then
      return 0
    fi
    sleep 3
  done

  return 1
}

on_failure() {
  local exit_code=$?
  trap - ERR INT TERM

  err "Deploy interrumpido en: $CURRENT_STEP"
  notify "Pricing App - EL DEPLOY FALLÓ

Se cortó en: ${CURRENT_STEP}
Duración hasta el corte: $(fmt_duration "$SECONDS")

El sistema puede haber quedado a medias. Revisar el log del deploy antes de usar la app."

  exit "$exit_code"
}

trap on_failure ERR INT TERM

# 0) Aviso de inicio
if [ "$SKIP_BACKEND" = false ]; then
  notify "Pricing App - arranca el deploy

Vamos a reiniciar el backend, así que la app puede quedar sin responder un rato.
Demora estimada: ~${DEPLOY_ETA_MIN} min.

Les avisamos cuando esté todo arriba de nuevo."
else
  notify "Pricing App - arranca el deploy

Solo se actualiza el frontend, el backend no se reinicia.
Demora estimada: ~${DEPLOY_ETA_MIN} min.

Les avisamos cuando termine."
fi

cd "$PROJECT_DIR"

# 1) Git pull
if [ "$SKIP_PULL" = false ]; then
  CURRENT_STEP="git pull"
  log "Pulling latest changes..."
  git pull
else
  warn "Skipping git pull"
fi

# 2) Backend dependencies + migrations
if [ "$SKIP_BACKEND" = false ]; then
  if [ -f "$BACKEND_DIR/requirements.txt" ]; then
    CURRENT_STEP="instalación de dependencias del backend"
    log "Instalando dependencias backend..."
    source "$BACKEND_DIR/venv/bin/activate"
    pip install -q -r "$BACKEND_DIR/requirements.txt"

    CURRENT_STEP="migraciones (alembic upgrade head)"
    log "Ejecutando migraciones (alembic upgrade head)..."
    cd "$BACKEND_DIR"
    alembic upgrade head
    cd "$PROJECT_DIR"

    deactivate
  fi
else
  warn "Skipping backend"
fi

# 3) Frontend build
if [ "$SKIP_BUILD" = false ]; then
  CURRENT_STEP="instalación de dependencias del frontend"
  log "Instalando dependencias frontend..."
  cd "$FRONTEND_DIR"
  pnpm install --frozen-lockfile

  CURRENT_STEP="build del frontend"
  log "Building frontend..."
  pnpm run build
else
  warn "Skipping frontend build"
fi

# 4) Copiar sounds a dist (no están en git)
if [ -d "$FRONTEND_DIR/public/sounds" ]; then
  CURRENT_STEP="copia de sounds a dist"
  log "Copiando sounds a dist..."
  cp -r "$FRONTEND_DIR/public/sounds/" "$FRONTEND_DIR/dist/sounds/"
  SOUND_COUNT=$(ls "$FRONTEND_DIR/dist/sounds/"*.mp3 2>/dev/null | wc -l)
  log "  $SOUND_COUNT archivos de audio copiados"
else
  warn "No existe public/sounds/ — el pistoleado no va a tener audio"
fi

# 5) Restart backend
BACKEND_STATUS="no reiniciado"
if [ "$SKIP_BACKEND" = false ]; then
  CURRENT_STEP="restart del backend"
  log "Reiniciando backend..."
  sudo systemctl restart pricing-api 2>/dev/null || warn "No se pudo reiniciar el servicio (¿existe pricing-api.service?)"

  CURRENT_STEP="health check del backend"
  log "Esperando que el backend responda en $HEALTHCHECK_URL..."
  if wait_for_backend; then
    BACKEND_STATUS="arriba"
    log "Backend respondiendo"
  else
    BACKEND_STATUS="sin responder"
    warn "El backend no respondió el health check en ${HEALTHCHECK_TIMEOUT}s"
  fi
fi

# 6) Aviso de cierre
CURRENT_STEP="aviso final"
DURATION=$(fmt_duration "$SECONDS")

if [ "$BACKEND_STATUS" = "sin responder" ]; then
  # Sin backend arriba no tiene sentido pedir que refresquen: la app no anda.
  FINAL_MSG="Pricing App - deploy terminado CON PROBLEMAS

El deploy terminó (${DURATION}) pero el backend no contesta el health check.
Todavía NO usen la app.
Revisar: sudo systemctl status pricing-api"
else
  FINAL_MSG="Pricing App - deploy terminado

Ya está todo arriba y funcionando. Demoró ${DURATION}."

  if [ "$SKIP_BUILD" = false ]; then
    FINAL_MSG="$FINAL_MSG

Se actualizó el frontend: refrescá la app con Ctrl+Shift+R (Cmd+Shift+R en Mac) para tomar la versión nueva."
  fi
fi

notify "$FINAL_MSG"

trap - ERR INT TERM
log "Deploy completado en $DURATION"
