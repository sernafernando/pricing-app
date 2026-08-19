#!/usr/bin/env bash
# Asks wabot whether an announced deploy has been vetoed from the WhatsApp group.
#
# Usage:
#   check-deploy-veto.sh <deploy_id>
#
# Contract -- deliberately NOT the always-exit-0 contract of notify-wabot.sh:
#   0   not vetoed, go ahead
#   10  vetoed  (HTTP 409 and nothing else)
#   20  could not tell: unreachable, timeout, bad token, unknown id, corrupt
#       state, malformed reply, missing argument
#
# The caller fails open on 20, so 10 must be impossible to reach by accident.
# That is why the verdict is read from the HTTP status code and never from the
# body: jq is optional on this host (see notify-wabot.sh), and a grep over
# `"vetoed":false` that guesses wrong would not fail loudly -- it would run a
# deploy somebody asked to stop.
#
# On exit 10 the vetoer's name is printed on stdout when jq is available. That
# is cosmetic: without jq the name degrades, the verdict never does.
#
# Reads WABOT_URL / WABOT_TOKEN / WABOT_TIMEOUT the same way notify-wabot.sh
# does: environment first, then the project's .env files, never by sourcing them.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

WABOT_ENV_FILES="$PROJECT_DIR/.env $PROJECT_DIR/backend/.env /etc/wabot-client.env"

# Same reasoning as notify-wabot.sh: these files hold DB credentials and
# third-party tokens that have no business entering a process that talks to the
# network, and an undefined $VAR inside one would kill this script under `set -u`.
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

if [ -z "$DEPLOY_ID" ]; then
    echo "check-deploy-veto: missing deploy id" >&2
    exit 20
fi

# Same allowlist the service enforces. The id is a URL path segment here and a
# filename there, so it is restricted rather than escaped.
if ! printf '%s' "$DEPLOY_ID" | grep -qE '^[A-Za-z0-9._-]{1,64}$'; then
    echo "check-deploy-veto: invalid deploy id" >&2
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
    echo "check-deploy-veto: WABOT_TOKEN not set, cannot check the veto" >&2
    exit 20
fi

BODY_FILE=$(mktemp) || exit 20
trap 'rm -f "$BODY_FILE"' EXIT

HTTP_CODE=$(curl -s -o "$BODY_FILE" -w '%{http_code}' \
    --max-time "$WABOT_TIMEOUT" \
    -H "Authorization: Bearer ${WABOT_TOKEN}" \
    "${WABOT_URL}/deploy/veto/${DEPLOY_ID}" 2>/dev/null) || HTTP_CODE="000"

case "$HTTP_CODE" in
    200)
        exit 0
        ;;
    409)
        if command -v jq >/dev/null 2>&1; then
            jq -r '.vetoed_by // empty' "$BODY_FILE" 2>/dev/null
        fi
        exit 10
        ;;
    000) echo "check-deploy-veto: unreachable (timeout or firewall)" >&2 ;;
    401) echo "check-deploy-veto: bad token (401)" >&2 ;;
    404) echo "check-deploy-veto: deploy ${DEPLOY_ID} unknown or expired (404)" >&2 ;;
    500) echo "check-deploy-veto: wabot cannot read its own veto state (500)" >&2 ;;
    *)   echo "check-deploy-veto: unexpected reply (HTTP ${HTTP_CODE})" >&2 ;;
esac

exit 20
