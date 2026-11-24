#!/bin/bash
# Deploy script - Pricing App Frontend
# Uso: ./deploy.sh [--skip-pull] [--skip-build] [--skip-backend] [--no-notify]
#                  [--minutes N] [--unstoppable]
#
# --minutes N avisa por WhatsApp que en ~N minutos arranca el deploy, espera ese
# rato y recién después empieza. Sirve para que el equipo corte lo que está
# haciendo sin tener que avisar a mano. Durante esa espera cualquiera del grupo
# puede responder "stop" y el deploy se cancela antes de tocar nada.
#
# --unstoppable es para el deploy urgente que va igual. Avisa y espera lo mismo,
# pero no se puede frenar desde el grupo -- y el aviso lo dice con todas las
# letras, porque un botón de pánico que a veces no funciona es peor que no
# tenerlo.
#
# Avisa por WhatsApp (wabot) al arrancar y al terminar. El aviso es best-effort:
# nunca puede romper ni frenar el deploy.
#
# Variables de entorno opcionales:
#   DEPLOY_ETA_MIN      minutos estimados que se comunican al equipo (default 5)
#   HEALTHCHECK_URL     URL que se consulta para confirmar que el backend levantó
#   HEALTHCHECK_TIMEOUT segundos máximos de espera del health check (default 120)
#   WABOT_TOKEN         token del servicio; si falta, el helper no manda nada
#   FRONTEND_NODE_DIR   Node con el que se buildea el frontend (default /opt/node24);
#                       si no está instalado se usa el node del PATH
#   BUILD_MIN_FREE_MB   memoria disponible (MemAvailable) mínima para buildear el
#                       frontend; con menos, el deploy se cancela antes de tocar nada
#   BUILD_MAX_HEAP_MB   tope del heap de Node para el build (--max-old-space-size)
#   BUILD_MEM_RESERVE_MB memoria disponible que no va al heap de Node: lo que el build usa
#                       fuera del heap (esbuild, workers de terser) más margen para el server
#   BUILD_TERSER_WORKERS workers de terser del build (default 2; vite usaría uno por CPU)

# -E propaga el trap ERR a las funciones; sin eso un fallo adentro de una
# función no dispararía el aviso de deploy fallido.
set -eE

# Overridable so the deploy can be exercised against a scratch tree in tests.
PROJECT_DIR="${PROJECT_DIR:-/srv/apps/pricing-app}"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKEND_DIR="$PROJECT_DIR/backend"
# El frontend se buildea con un Node aparte para no tener que actualizar /usr/bin/node,
# que puede usar otro software del contenedor (LXC apps en xenon).
FRONTEND_NODE_DIR="${FRONTEND_NODE_DIR:-/opt/node24}"

NOTIFY_SCRIPT="$PROJECT_DIR/scripts/notify-wabot.sh"
ANNOUNCE_SCRIPT="$PROJECT_DIR/scripts/announce-deploy.sh"
WORKERS_SCRIPT="$PROJECT_DIR/scripts/restart-verify-workers.sh"
VETO_SCRIPT="$PROJECT_DIR/scripts/check-deploy-veto.sh"
# Cada cuánto se le pregunta a wabot si alguien frenó el deploy.
VETO_POLL_SECONDS="${VETO_POLL_SECONDS:-10}"
DEPLOY_ETA_MIN="${DEPLOY_ETA_MIN:-5}"
# El /health se sirve por el reverse proxy. El puerto crudo del backend
# (8000) devuelve 404 en esa ruta, así que no sirve para verificar nada.
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://pricing.gaussonline.com.ar/health}"
HEALTHCHECK_TIMEOUT="${HEALTHCHECK_TIMEOUT:-120}"

# Memoria del build del frontend. El 22/11 el OOM killer mató el build dos veces (exit 137) con
# servicios viejos ocupando ~9 de 16 GB, y como vite ya había vaciado dist el sitio quedó caído una
# hora. Ahora el build va a dist.new y solo se publica si terminó bien, y antes de arrancar se mira
# la memoria: sin suficiente, se corta con un mensaje claro en vez de morir a mitad del build.
#
# Medido (Node 24.22.1, mismo lockfile, RSS sumado de todo el árbol de procesos): con el default de
# vite (11 workers de terser en 12 CPUs) el pico es ~8,0 GB; con 2 workers ~5,8 GB, igual con heap de
# 3072 o 4096 MB. Con heap de 2560 MB o menos el build muere por heap. De ahí:
#   - heap = disponible - reserva, tope 4096 (el default de Node 24 es ~4288);
#   - reserva 3500: ~2,8 GB que el build usa fuera del heap, más margen para el resto del server;
#   - mínimo 6600 = el heap más chico que anda (3072) + la reserva.
BUILD_MIN_FREE_MB="${BUILD_MIN_FREE_MB:-6600}"
BUILD_MAX_HEAP_MB="${BUILD_MAX_HEAP_MB:-4096}"
BUILD_MEM_RESERVE_MB="${BUILD_MEM_RESERVE_MB:-3500}"
BUILD_MIN_HEAP_MB=3072
# Cada worker de terser es un thread con su heap propio, y vite pone uno por CPU menos uno: ese
# pool es el que se come la RAM. Con 2 el resultado es idéntico byte a byte (vite.config.js).
BUILD_TERSER_WORKERS="${BUILD_TERSER_WORKERS:-2}"
# Overridable para los tests.
MEMINFO_FILE="${MEMINFO_FILE:-/proc/meminfo}"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

# Corre un comando como root: directo si ya somos root (LXC de xenon, que no trae `sudo`), con
# sudo si no. Sin esto, en el LXC el restart fallaba contra un `sudo` inexistente y solo avisaba.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

# MemAvailable en MB: lo libre más la caché que el kernel puede soltar, que es lo que de verdad
# puede usar el build. Sale distinto de 0 si no se puede leer.
mem_available_mb() {
  awk '/^MemAvailable:/ { printf "%d\n", $2 / 1024; ok = 1 } END { exit !ok }' "$MEMINFO_FILE" 2>/dev/null
}

# Mira si hay memoria para el build y deja en BUILD_HEAP_MB el heap que puede usar Node: lo
# disponible menos la reserva, con el tope BUILD_MAX_HEAP_MB. Sale 1 si no alcanza (deja en
# AVAIL_MB lo que hay). Si no se puede leer la memoria, avisa y sigue con el tope: no saber no es
# motivo para frenar un deploy.
build_memory_ok() {
  if ! AVAIL_MB=$(mem_available_mb); then
    warn "No se pudo leer la memoria disponible ($MEMINFO_FILE): se buildea con heap de ${BUILD_MAX_HEAP_MB} MB sin chequear"
    BUILD_HEAP_MB=$BUILD_MAX_HEAP_MB
    return 0
  fi
  # Nunca menos que la reserva más el heap más chico con el que el build anda: con menos muere igual,
  # y un heap negativo Node lo ignora en silencio (usa su default). Pasa si alguien baja
  # BUILD_MIN_FREE_MB por debajo de la reserva.
  BUILD_NEED_MB=$BUILD_MIN_FREE_MB
  [ "$BUILD_NEED_MB" -ge $((BUILD_MEM_RESERVE_MB + BUILD_MIN_HEAP_MB)) ] ||
    BUILD_NEED_MB=$((BUILD_MEM_RESERVE_MB + BUILD_MIN_HEAP_MB))
  [ "$AVAIL_MB" -ge "$BUILD_NEED_MB" ] || return 1
  BUILD_HEAP_MB=$((AVAIL_MB - BUILD_MEM_RESERVE_MB))
  [ "$BUILD_HEAP_MB" -le "$BUILD_MAX_HEAP_MB" ] || BUILD_HEAP_MB=$BUILD_MAX_HEAP_MB
  return 0
}

# Lo que más memoria ocupa, para que el mensaje diga a quién hay que mirar.
top_memory() {
  ps -eo rss=,comm= --sort=-rss 2>/dev/null | head -5 | awk '{ printf "  %6d MB  %s\n", $1 / 1024, $2 }'
}

# Publica el build nuevo: dist pasa a dist.prev (queda para volver atrás a mano) y dist.new a dist.
# Con `mv --exchange` (coreutils >= 9.5) el cambio es atómico; si no está, son dos renames
# seguidos y dist falta solo entre uno y otro. Nunca queda dist vacío ni a medio escribir.
publish_dist() {
  local dist=$1 new=$2 prev=$3
  rm -rf "$prev"
  if [ ! -d "$dist" ]; then
    mv "$new" "$dist"
  elif mv -T --exchange "$new" "$dist" 2>/dev/null; then
    # Ya está publicado: si guardar el anterior falla, es un aviso, no un deploy fallido.
    DIST_PUBLISHED=yes
    mv "$new" "$prev" || warn "El build nuevo ya está publicado, pero el anterior no se pudo guardar en $prev (quedó en $new)"
  else
    # Entre los dos renames dist no existe: un Ctrl+C o un TERM justo ahí cortaría el deploy con
    # el sitio sin frontend. Las señales se ignoran solo durante estos dos mv.
    trap '' INT TERM
    mv "$dist" "$prev"
    mv "$new" "$dist" || { mv "$prev" "$dist"; trap on_failure INT TERM; return 1; }
    trap on_failure INT TERM
  fi
}

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
UNSTOPPABLE=false

while [ $# -gt 0 ]; do
  case $1 in
    --skip-pull) SKIP_PULL=true ;;
    --skip-build) SKIP_BUILD=true ;;
    --skip-backend) SKIP_BACKEND=true ;;
    --no-notify) NOTIFY=false ;;
    --unstoppable) UNSTOPPABLE=true ;;
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
# "no" mientras el build está en curso y el dist publicado sigue siendo el anterior.
DIST_PUBLISHED=""

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

# El deploy se cancela porque alguien lo frenó desde el grupo. NO es una falla:
# se desarma el trap ANTES de avisar, si no on_failure manda "EL DEPLOY FALLÓ"
# por un final perfectamente ordenado en el que no se tocó una sola línea.
abort_vetoed() {
  local quien=${1:-}
  [ -n "$quien" ] || quien="alguien del grupo"

  trap - ERR INT TERM

  warn "Deploy frenado desde el grupo por ${quien}. No se tocó nada."
  notify "Pricing App - deploy cancelado

Lo frenó ${quien} desde el grupo. No se tocó nada, la app sigue funcionando normalmente.

Avisamos cuando lo reprogramemos."

  exit 75
}

# No hay memoria para buildear el frontend. Se corta ANTES de tocar nada (ni pull, ni
# migraciones, ni dist): igual que un veto, no es un deploy fallido a medias.
abort_low_memory() {
  trap - ERR INT TERM

  err "Memoria insuficiente para buildear el frontend: hay ${AVAIL_MB} MB disponibles y hacen falta ${BUILD_NEED_MB} MB."
  err "Lo que más memoria ocupa:"
  top_memory >&2
  err "Liberá memoria (servicios viejos o colgados) y volvé a correr el deploy. No se tocó nada."
  notify "Pricing App - deploy cancelado

No hay memoria libre suficiente en el servidor para buildear el frontend (${AVAIL_MB} MB disponibles, hacen falta ${BUILD_NEED_MB} MB). No se tocó nada, la app sigue funcionando normalmente.

Avisamos cuando lo reprogramemos."

  exit 1
}

# Se imprime en CADA poll fallido, no una sola vez. Si el preaviso salió bien y
# después wabot se cayó, el grupo cree que su "stop" sirve y no sirve: el deploy
# sigue igual (fail-open, a propósito) y el que lo está corriendo tiene que
# poder enterarse sin leer un log.
veto_banner() {
  echo -e "${RED}" >&2
  echo "  ###############################################################" >&2
  echo "  #  NO SE PUEDE CONSULTAR EL FRENO                             #" >&2
  echo "  #  wabot no contesta. El deploy SIGUE porque así está pensado, #" >&2
  echo "  #  pero si alguien mandó 'stop' al grupo no nos vamos a        #" >&2
  echo "  #  enterar. Cortá con Ctrl+C si querés jugar a lo seguro.      #" >&2
  echo "  ###############################################################" >&2
  echo -e "${NC}" >&2
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

  # Un build que se cae no toca el frontend publicado: va a dist.new y solo se cambia por dist
  # si terminó bien. Decirlo evita que el equipo crea que la app quedó sin frontend.
  local dist_note=""
  if [ "$DIST_PUBLISHED" = no ]; then
    dist_note="

El frontend publicado no se tocó: la app sigue con la versión anterior."
    err "dist no se tocó: sigue publicado el frontend anterior (lo que haya dejado el build está en dist.new)"
  fi

  notify "Pricing App - EL DEPLOY FALLÓ

Se cortó en: ${CURRENT_STEP}
Duración hasta el corte: $(fmt_duration "$SECONDS")

El sistema puede haber quedado a medias. Revisar el log del deploy antes de usar la app.${dist_note}"

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

  DEPLOY_ID="$(date +%s)-$$"

  if [ "$UNSTOPPABLE" = true ]; then
    ANNOUNCE_MSG="Pricing App - deploy en ${WAIT_LABEL}

En aproximadamente ${WAIT_LABEL} vamos a realizar un deploy.

Durante el proceso la app puede quedar sin responder por unos minutos.

Este deploy NO se puede frenar: es urgente y va igual.

Avisamos cuando arranque y nuevamente cuando esté todo arriba."
  else
    ANNOUNCE_MSG="Pricing App - deploy en ${WAIT_LABEL}

En aproximadamente ${WAIT_LABEL} vamos a realizar un deploy.

Durante el proceso la app puede quedar sin responder por unos minutos.

Si justo estás en el medio de algo, respondé *stop* en este grupo y lo frenamos.

Avisamos cuando arranque y nuevamente cuando esté todo arriba."
  fi

  # El anuncio manda el mensaje Y registra el deploy para que el "stop" del
  # grupo tenga algo que vetar. Si falla no se corta nada: se sigue esperando y
  # el poll de abajo va a contestar "no puedo saber", que es la verdad.
  # OJO con la doble negacion: el helper recibe `stoppable`, no `unstoppable`.
  # Pasar $UNSTOPPABLE directo anunciaba stoppable=false en los deploys que SI
  # se podian frenar, y el bot rechazaba el "stop" con el mensaje de emergencia
  # aunque el aviso acabara de invitar a frenarlo.
  if [ "$UNSTOPPABLE" = true ]; then
    STOPPABLE_FLAG=false
  else
    STOPPABLE_FLAG=true
  fi

  if [ "$NOTIFY" = true ] && [ -r "$ANNOUNCE_SCRIPT" ]; then
    bash "$ANNOUNCE_SCRIPT" "$DEPLOY_ID" "$WAIT_MINUTES" "$STOPPABLE_FLAG" "$ANNOUNCE_MSG" || \
      warn "No se pudo anunciar el deploy a wabot"
  else
    warn "Sin aviso por WhatsApp: nadie se entera de este deploy ni puede frenarlo"
  fi

  if [ "$UNSTOPPABLE" = true ]; then
    log "Preaviso enviado (deploy NO frenable). Esperando ${WAIT_LABEL}..."
    sleep $((WAIT_MINUTES * 60))
  else
    log "Preaviso enviado. Esperando ${WAIT_LABEL} — el grupo puede frenarlo con 'stop'..."

    VETO_DEADLINE=$((SECONDS + WAIT_MINUTES * 60))
    while [ "$SECONDS" -lt "$VETO_DEADLINE" ]; do
      # La llamada va en contexto de condición a propósito: el helper sale
      # distinto de 0 por diseño, y bajo `set -eE` eso dispararía el trap ERR
      # convirtiendo un veto limpio en un "EL DEPLOY FALLÓ".
      VETO_OUT=$(bash "$VETO_SCRIPT" "$DEPLOY_ID") && VETO_RC=0 || VETO_RC=$?

      case "$VETO_RC" in
        0)  ;;
        10) abort_vetoed "$VETO_OUT" ;;
        *)  veto_banner ;;
      esac

      VETO_LEFT=$((VETO_DEADLINE - SECONDS))
      [ "$VETO_LEFT" -le 0 ] && break
      if [ "$VETO_LEFT" -lt "$VETO_POLL_SECONDS" ]; then
        sleep "$VETO_LEFT"
      else
        sleep "$VETO_POLL_SECONDS"
      fi
    done
  fi
fi

# 0b) Memoria para el build: se mira antes de avisar y de tocar nada, así un servidor sin memoria
# cancela el deploy limpio en vez de dejarlo a medias. Se vuelve a mirar justo antes del build.
if [ "$SKIP_BUILD" = false ]; then
  CURRENT_STEP="chequeo de memoria para el build"
  build_memory_ok || abort_low_memory
  log "Memoria disponible: ${AVAIL_MB:-?} MB (mínimo para el build: ${BUILD_NEED_MB:-$BUILD_MIN_FREE_MB} MB)"
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
  FRONTEND_PATH="$PATH"
  if [ -x "$FRONTEND_NODE_DIR/bin/node" ]; then
    FRONTEND_PATH="$FRONTEND_NODE_DIR/bin:$PATH"
  else
    # Fallback deliberado en vez de fallar: a esta altura las migraciones ya corrieron, y cortar
    # acá dejaría el deploy a medias. El aviso muestra con qué Node se buildea.
    warn "No está $FRONTEND_NODE_DIR/bin/node: el frontend se buildea con el node del PATH ($(node --version 2>/dev/null || echo 'no encontrado')), no con el que usa CI"
  fi
  # El PATH del Node aparte vale solo para pnpm: el resto del deploy sigue con el de siempre.
  # Sin el prompt de corepack, un deploy sin terminal no se queda esperando al bajar pnpm.
  frontend_pnpm() { PATH="$FRONTEND_PATH" COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm "$@"; }

  CURRENT_STEP="instalación de dependencias del frontend"
  log "Instalando dependencias frontend (Node $(PATH="$FRONTEND_PATH" node --version 2>/dev/null || echo '?'))..."
  cd "$FRONTEND_DIR"
  frontend_pnpm install --frozen-lockfile

  # Se buildea en dist.new y dist sigue sirviendo la versión anterior hasta el swap: un build que
  # muere (OOM, exit 137) ya no puede dejar el sitio sin frontend, porque vite vacía su outDir al
  # arrancar y ese outDir ya no es el publicado.
  DIST_DIR="$FRONTEND_DIR/dist"
  DIST_NEW="$FRONTEND_DIR/dist.new"
  DIST_PREV="$FRONTEND_DIR/dist.prev"
  DIST_PUBLISHED=no

  # La memoria puede haber bajado durante pip y las migraciones: se vuelve a mirar con dist intacto.
  CURRENT_STEP="chequeo de memoria para el build"
  if ! build_memory_ok; then
    err "Memoria insuficiente para buildear el frontend: hay ${AVAIL_MB} MB disponibles y hacen falta ${BUILD_NEED_MB} MB."
    err "Lo que más memoria ocupa:"
    top_memory >&2
    false
  fi

  CURRENT_STEP="build del frontend"
  log "Building frontend..."
  log "  en dist.new con heap de Node de ${BUILD_HEAP_MB} MB y ${BUILD_TERSER_WORKERS} workers de terser (dist sigue publicado hasta que termine bien)"
  NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=${BUILD_HEAP_MB}" \
    BUILD_TERSER_WORKERS="$BUILD_TERSER_WORKERS" \
    frontend_pnpm run build --outDir "$DIST_NEW" --emptyOutDir

  CURRENT_STEP="publicación del build (dist.new -> dist)"
  if [ ! -s "$DIST_NEW/index.html" ]; then
    err "El build terminó pero no dejó $DIST_NEW/index.html: no se publica"
    false
  fi
  publish_dist "$DIST_DIR" "$DIST_NEW" "$DIST_PREV"
  DIST_PUBLISHED=yes
  log "Build publicado en dist (la versión anterior quedó en dist.prev)"
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
  as_root systemctl restart pricing-api 2>/dev/null || warn "No se pudo reiniciar el servicio (¿existe pricing-api.service?)"

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

# 6b) Restart y verificación de los workers (pricing-worker y pricing-worker-ml, design D1).
# Warn, no fail: la unit de systemd la instala el owner a mano y puede no existir en todos los
# entornos, y un worker caído nunca debe tumbar un deploy que ya dejó el backend arriba. Pero
# tampoco se da por bueno un worker sólo porque `restart` volvió: el script espera a que cada
# uno esté activo Y a que su heartbeat en worker_job_state avance. Un proceso vivo con el
# heartbeat clavado (colgado) se reporta igual. Cada falla sale como una línea
# `PROBLEM <unit>: <motivo>` y termina en el aviso final como "CON PROBLEMAS". El deploy no
# habilita nunca pricing-worker-ml: sólo lo reinicia si el owner ya lo habilitó.
WORKERS_PROBLEMS=""
CURRENT_STEP="restart y verificación de los workers"
if [ "$SKIP_BACKEND" = false ]; then
  log "Reiniciando y verificando los workers (pricing-worker, pricing-worker-ml)..."
  if [ -r "$WORKERS_SCRIPT" ]; then
    # En contexto de condición a propósito: el script sale 1 cuando hay problemas y, bajo
    # `set -eE`, eso dispararía el trap ERR y cortaría el deploy.
    WORKERS_PROBLEMS=$(bash "$WORKERS_SCRIPT") || true
  else
    warn "No se pudo leer $WORKERS_SCRIPT — los workers no se reiniciaron ni se verificaron"
    WORKERS_PROBLEMS="PROBLEM workers: no se encontró $WORKERS_SCRIPT (no se reiniciaron ni se verificaron)"
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
  if [ -n "$WORKERS_PROBLEMS" ]; then
    FINAL_MSG="$FINAL_MSG

Además falló la verificación de los workers:
${WORKERS_PROBLEMS//PROBLEM /- }"
  fi
elif [ -n "$WORKERS_PROBLEMS" ]; then
  # El backend responde, así que la app se puede usar; lo que falla es un worker.
  FINAL_MSG="Pricing App - deploy terminado CON PROBLEMAS

El deploy terminó (${DURATION}) y el backend está arriba, pero falló la verificación de los workers:
${WORKERS_PROBLEMS//PROBLEM /- }

La app se puede usar, pero lo que dependa de ese worker no se está procesando.
Revisar: sudo systemctl status <worker> y journalctl -u <worker>"

  if [ "$SKIP_BUILD" = false ]; then
    FINAL_MSG="$FINAL_MSG

Se actualizó el frontend: refrescá la app con Ctrl+Shift+R (Cmd+Shift+R en Mac) para tomar la versión nueva."
  fi
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
