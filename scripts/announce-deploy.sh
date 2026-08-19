#!/usr/bin/env bash
# Announces a pending deploy to the WhatsApp group AND registers it with wabot
# so the group's "stop" has something to veto.
#
# Usage:
#   announce-deploy.sh <deploy_id> <minutes> <stoppable:true|false> <message>
#
# Contract:
#   0   announced and registered
#   20  anything else (unreachable, bad token, rejected payload, send failure)
#
# Exit 20 is NOT fatal for the caller: deploy.sh keeps waiting and keeps polling,
# which then answers 404 -> "cannot tell" -> the loud banner. That is the honest
# state -- we announced nothing, so we cannot hear a stop either -- and it needs
# no second code path.
#
# Kept separate from deploy.sh so the token and the curl live here, exactly like
# notify-wabot.sh.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

WABOT_ENV_FILES="$PROJECT_DIR/.env $PROJECT_DIR/backend/.env /etc/wabot-client.env"

read_env_key() {
    local file=$1 key=$2 value
    [ -r "$file" ] || return 1

    value=$(sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)
    value=${value%$'\r'}

    case $value in
        \"*\") value=${value#\"}; value=${value%\"} ;;
        \'*\') value=${value#\'}; value=${value%\'} ;;
    esac

    [ -n "$value" ] || return 1
    printf '%s' "$value"
}

DEPLOY_ID="${1:-}"
MINUTES="${2:-}"
STOPPABLE="${3:-}"
MESSAGE="${4:-}"

if [ -z "$DEPLOY_ID" ] || [ -z "$MINUTES" ] || [ -z "$STOPPABLE" ] || [ -z "$MESSAGE" ]; then
    echo "announce-deploy: usage: announce-deploy.sh <deploy_id> <minutes> <true|false> <message>" >&2
    exit 20
fi

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

if [ -z "${WABOT_TOKEN:-}" ]; then
    echo "announce-deploy: WABOT_TOKEN not set, nothing announced" >&2
    exit 20
fi

# jq builds the JSON so accents and newlines in the message cannot break the
# payload. Without jq we cannot safely build it, and announcing a mangled
# message is worse than not announcing: exit 20 and let the caller be loud.
if ! command -v jq >/dev/null 2>&1; then
    echo "announce-deploy: jq is required to build the payload safely" >&2
    exit 20
fi

PAYLOAD=$(jq -nc \
    --arg id "$DEPLOY_ID" \
    --argjson min "$MINUTES" \
    --argjson stop "$STOPPABLE" \
    --arg msg "$MESSAGE" \
    '{deploy_id:$id, minutes:$min, stoppable:$stop, message:$msg}') || exit 20

HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
    --max-time "$WABOT_TIMEOUT" \
    -X POST "${WABOT_URL}/deploy/announce" \
    -H "Authorization: Bearer ${WABOT_TOKEN}" \
    -H 'content-type: application/json' \
    -d "$PAYLOAD" 2>/dev/null) || HTTP_CODE="000"

case "$HTTP_CODE" in
    200) exit 0 ;;
    000) echo "announce-deploy: unreachable (timeout or firewall)" >&2 ;;
    401) echo "announce-deploy: bad token (401)" >&2 ;;
    400) echo "announce-deploy: wabot rejected the announcement (400)" >&2 ;;
    502) echo "announce-deploy: registered but WhatsApp send failed (502)" >&2 ;;
    503) echo "announce-deploy: service not linked (503)" >&2 ;;
    *)   echo "announce-deploy: failed (HTTP ${HTTP_CODE})" >&2 ;;
esac

exit 20
