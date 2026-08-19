#!/bin/bash
# Deploy script - Pricing App Frontend
# Uso: ./deploy.sh [--skip-pull] [--skip-build] [--skip-backend] [--no-notify]
#                  [--minutes N]
#
# --minutes N avisa por WhatsApp que en ~N minutos arranca el deploy, espera ese
# rato y recién después empieza. Sirve para que el equipo corte lo que está
# haciendo sin tener que avisar a mano.
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

# ponytail (docs/tech-debt-ledger.md): todo el cuerpo ejecutable vive adentro de
# main() y se invoca al final del archivo. Bash lee los scripts por chunks
# llevando un offset de byte, asi que el `git pull` de mas abajo -- que reescribe
# ESTE archivo mientras bash todavia lo esta leyendo -- hacia que la ejecucion
# siguiera desde ese offset pero sobre el archivo nuevo: corrian fragmentos
# arbitrarios, o el script terminaba en silencio sin build ni restart. Con el
# cuerpo adentro de una funcion, bash tiene que parsearla entera antes de
# ejecutar una sola linea, de modo que el pull ya no puede cortar el script a la
# mitad. La indentacion se deja como estaba a proposito: reindentar 200 lineas
# esconderia el cambio real en ruido de whitespace y alteraria el texto de los
# mensajes multilinea que se mandan al grupo.
main() {

SKIP_PULL=false
SKIP_BUILD=false
SKIP_BACKEND=false
NOTIFY=true
WAIT_MINUTES=0

while [ $# -gt 0 ]; do
  case $1 in
    --skip-pull) SKIP_PULL=true ;;
    --skip-build) SKIP_BUILD=true ;;
    --skip-backend) SKIP_BACKEND=true ;;
    --no-notify) NOTIFY=false ;;
    --minutes=*) WAIT_MINUTES="${1#*=}" ;;
    --minutes)
      # El valor viene en el argumento siguiente; consumirlo acá evita que el
      # loop lo lea después como si fuera una flag desconocida.
      WAIT_MINUTES="${2:-}"
      shift
      ;;
    *) warn "Argumento desconocido: $1" ;;
  esac
  shift
done

# Se valida antes de tocar nada: un --minutes mal escrito tiene que cortar acá y
# no después de haber avisado al equipo o arrancado el deploy.
if ! [[ "$WAIT_MINUTES" =~ ^[0-9]+$ ]]; then
  err "--minutes espera un número entero de minutos (recibido: '${WAIT_MINUTES}')"
  exit 1
fi

# Paso actual, para poder decir en qué se cortó si el deploy falla.
CURRENT_STEP="inicio"

# Manda un aviso por WhatsApp. El helper siempre sale 0, pero el `|| true`
# deja explícito que un fallo de notificación jamás corta el deploy.
notify() {
  [ "$NOTIFY" = true ] || return 0

  # Se chequea -r y se invoca con `bash` explicito, NO -x: el repo versiona los
  # .sh como 100644 (core.fileMode=false), asi que el archivo llega del git pull
  # sin bit ejecutable y un guard por -x dejaria la feature muda en silencio.
  if [ ! -r "$NOTIFY_SCRIPT" ]; then
    warn "No se pudo leer $NOTIFY_SCRIPT — sin aviso por WhatsApp"
    return 0
  fi

  bash "$NOTIFY_SCRIPT" "$1" || true
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

  # Cortarse durante la espera previa es distinto a cortarse a mitad del deploy:
  # todavía no se tocó nada, y el equipo ya recibió el preaviso. Decir "puede
  # haber quedado a medias" acá asustaría sin motivo.
  if [ "$CURRENT_STEP" = "espera previa al deploy" ]; then
    notify "Pricing App - deploy cancelado

Se suspendió el deploy que habíamos anunciado. No se tocó nada, la app sigue funcionando normalmente.

Avisamos cuando lo reprogramemos."
    exit "$exit_code"
  fi

  notify "Pricing App - EL DEPLOY FALLÓ

Se cortó en: ${CURRENT_STEP}
Duración hasta el corte: $(fmt_duration "$SECONDS")

El sistema puede haber quedado a medias. Revisar el log del deploy antes de usar la app."

  exit "$exit_code"
}

trap on_failure ERR INT TERM

# 0) Preaviso + espera
if [ "$WAIT_MINUTES" -gt 0 ]; then
  CURRENT_STEP="espera previa al deploy"

  if [ "$WAIT_MINUTES" -eq 1 ]; then
    WAIT_LABEL="1 min"
  else
    WAIT_LABEL="${WAIT_MINUTES} min"
  fi

  notify "Pricing App - deploy en ${WAIT_LABEL}

En aproximadamente ${WAIT_LABEL} vamos a realizar un deploy.

Durante el proceso la app puede quedar sin responder por unos minutos.

Avisamos cuando arranque y nuevamente cuando esté todo arriba."

  log "Preaviso enviado. Esperando ${WAIT_LABEL} antes de arrancar..."
  sleep $((WAIT_MINUTES * 60))
fi

# 1) Aviso de inicio
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

# 2) Git pull
if [ "$SKIP_PULL" = false ]; then
  CURRENT_STEP="git pull"
  log "Pulling latest changes..."
  # ponytail: este pull puede reescribir deploy.sh mientras bash todavia lo esta
  # leyendo, y bash sigue leyendo por offset de byte sobre el archivo nuevo — el
  # deploy se corta en silencio. Blindaje: envolver el cuerpo en main() { ... }.
  # Mientras tanto: git pull a mano ANTES de correr ./deploy.sh cuando este
  # archivo cambio. Ver docs/tech-debt-ledger.md.
  git pull
else
  warn "Skipping git pull"
fi

# 3) Backend dependencies + migrations
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

# 4) Frontend build
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

# 5) Copiar sounds a dist (no están en git)
if [ -d "$FRONTEND_DIR/public/sounds" ]; then
  CURRENT_STEP="copia de sounds a dist"
  log "Copiando sounds a dist..."
  cp -r "$FRONTEND_DIR/public/sounds/" "$FRONTEND_DIR/dist/sounds/"
  SOUND_COUNT=$(ls "$FRONTEND_DIR/dist/sounds/"*.mp3 2>/dev/null | wc -l)
  log "  $SOUND_COUNT archivos de audio copiados"
else
  warn "No existe public/sounds/ — el pistoleado no va a tener audio"
fi

# 6) Restart backend
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

# 7) Aviso de cierre
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

}

main "$@"
