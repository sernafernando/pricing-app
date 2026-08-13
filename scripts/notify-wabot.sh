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
# Reads WABOT_TOKEN from the environment, or from /etc/wabot-client.env when
# present. Never hardcode the token in this file.
#
# Only these hosts can reach the service (firewall): 192.168.1.219,
# 192.168.1.228, 192.168.1.230.

set -uo pipefail

WABOT_URL="${WABOT_URL:-http://192.168.1.232:3000}"
WABOT_TIMEOUT="${WABOT_TIMEOUT:-8}"

# El `set -u` de arriba convierte cualquier $VAR sin definir dentro del archivo
# (un placeholder sin expandir, un token mal pegado) en un error fatal que mata
# este helper y rompe su contrato de salir siempre 0. Se relaja solo acá: con un
# token invalido preferimos un 401 legible antes que una muerte silenciosa.
if [ -z "${WABOT_TOKEN:-}" ] && [ -r /etc/wabot-client.env ]; then
    set +u
    # shellcheck disable=SC1091
    . /etc/wabot-client.env
    set -u
fi

MESSAGE="${1:-}"

if [ -z "$MESSAGE" ]; then
    echo "notify-wabot: empty message, skipping" >&2
    exit 0
fi

if [ -z "${WABOT_TOKEN:-}" ]; then
    echo "notify-wabot: WABOT_TOKEN not set, skipping" >&2
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
