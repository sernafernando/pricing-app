#!/usr/bin/env bash
# Fail-safe WhatsApp notification helper for cron scripts.
#
# Usage:
#   notify-wabot.sh "db_backup.sh FAILED: pg_dump exit 1"
#
# Contract:
#   - ALWAYS exits 0. Adding this to a script can never change that script's
#     own exit status or break its error handling.
#   - Uses a hard timeout.
#   - Does not retry.
#
# Reads WABOT_URL / WABOT_TOKEN / WABOT_TIMEOUT from the environment, and
# otherwise from the project's own .env — which is where the wabot contract says
# the caller's token lives. Never hardcode the token in this file.
#
# Only these hosts can reach the service (firewall): 192.168.1.219,
# 192.168.1.228, 192.168.1.230.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

# Orden de resolucion: entorno > .env del proyecto > .env del backend >
# /etc/wabot-client.env (para instalaciones fuera del arbol del proyecto).
WABOT_ENV_FILES="$PROJECT_DIR/.env $PROJECT_DIR/backend/.env /etc/wabot-client.env"

# Extrae UNA clave de un archivo .env sin sourcearlo. Sourcear no es opcion:
# estos archivos traen credenciales de DB y tokens de terceros que no tienen por
# que entrar al entorno de un proceso que sale a la red, y ademas cualquier $VAR
# sin definir adentro mataria este helper por el `set -u` de arriba, rompiendo su
# contrato de salir siempre 0.
read_env_key() {
    local file=$1 key=$2 value
    [ -r "$file" ] || return 1

    value=$(sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)
    value=${value%$'\r'}

    # Saca comillas envolventes si el valor viene citado.
    case $value in
        \"*\") value=${value#\"}; value=${value%\"} ;;
        \'*\') value=${value#\'}; value=${value%\'} ;;
    esac

    [ -n "$value" ] || return 1
    printf '%s' "$value"
}

WABOT_URL="${WABOT_URL:-}"
WABOT_TOKEN="${WABOT_TOKEN:-}"
WABOT_TIMEOUT="${WABOT_TIMEOUT:-}"

for env_file in $WABOT_ENV_FILES; do
    [ -r "$env_file" ] || continue
    [ -n "$WABOT_TOKEN" ]   || WABOT_TOKEN=$(read_env_key "$env_file" WABOT_TOKEN || true)
    [ -n "$WABOT_URL" ]     || WABOT_URL=$(read_env_key "$env_file" WABOT_URL || true)
    [ -n "$WABOT_TIMEOUT" ] || WABOT_TIMEOUT=$(read_env_key "$env_file" WABOT_TIMEOUT || true)
done

WABOT_URL="${WABOT_URL:-http://192.168.1.232:3000}"
WABOT_TIMEOUT="${WABOT_TIMEOUT:-8}"

MESSAGE="${1:-}"

if [ -z "$MESSAGE" ]; then
    echo "notify-wabot: empty message, skipping" >&2
    exit 0
fi

if [ -z "${WABOT_TOKEN:-}" ]; then
    # Decir DONDE se busco: sin esto, un token puesto en el archivo equivocado se
    # ve exactamente igual que no haber puesto ninguno.
    echo "notify-wabot: WABOT_TOKEN not set, skipping. Looked in: \$WABOT_TOKEN," >&2
    for env_file in $WABOT_ENV_FILES; do
        if [ -r "$env_file" ]; then
            echo "  $env_file (readable, no WABOT_TOKEN key)" >&2
        else
            echo "  $env_file (not readable)" >&2
        fi
    done
    exit 0
fi

# jq builds the JSON so quotes, newlines and accents in $MESSAGE cannot break
# the payload. Falls back to a conservative escape when jq is unavailable.
if command -v jq >/dev/null 2>&1; then
    PAYLOAD=$(jq -nc --arg m "$MESSAGE" '{message:$m}')
else
    ESCAPED=${MESSAGE//\\/\\\\}
    ESCAPED=${ESCAPED//\"/\\\"}
    ESCAPED=${ESCAPED//$'\n'/\\n}
    PAYLOAD="{\"message\":\"${ESCAPED}\"}"
fi

HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
    --max-time "$WABOT_TIMEOUT" \
    -X POST "${WABOT_URL}/send" \
    -H "Authorization: Bearer ${WABOT_TOKEN}" \
    -H 'content-type: application/json' \
    -d "$PAYLOAD" 2>/dev/null) || HTTP_CODE="000"

case "$HTTP_CODE" in
    200) ;;
    000) echo "notify-wabot: unreachable (timeout or firewall)" >&2 ;;
    503) echo "notify-wabot: service not linked (503)" >&2 ;;
    401) echo "notify-wabot: bad token (401)" >&2 ;;
    *)   echo "notify-wabot: failed (HTTP ${HTTP_CODE})" >&2 ;;
esac

exit 0
