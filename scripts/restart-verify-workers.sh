#!/usr/bin/env bash
# Restarts the worker services after a deploy and VERIFIES each one, instead of trusting
# `systemctl restart` (which returns as soon as the process is forked).
#
# Workers (unit : heartbeat row in worker_job_state.name):
#   pricing-worker     : worker      always expected; a missing unit is a problem
#   pricing-worker-ml  : worker-ml   optional; a missing unit only warns, and an installed unit
#                                    that is neither enabled nor active is NOT started: the deploy
#                                    never turns the ML worker on, the operator does (design D1)
#
# A worker passes when, within WORKER_VERIFY_TIMEOUT seconds of its restart, BOTH hold:
#   - `systemctl is-active` says active, and
#   - its heartbeat row advanced past the value read BEFORE the restart. A process that is alive
#     but wedged (the heartbeat thread stopped) fails here: that is the "hung" case.
# The heartbeat is written every WORKER_HEARTBEAT_INTERVAL_SECONDS (5 s); the default timeout
# leaves room for the interpreter and imports to start.
#
# Output contract, so deploy.sh can build the announcement:
#   stdout: one `PROBLEM <unit>: <reason>` line per failure, nothing else
#   stderr: human log of every worker's state
#   exit:   0 all fine, 1 at least one problem. It never aborts the deploy: the caller warns.
#
# Environment (all optional): WORKER_VERIFY_TIMEOUT (45), WORKER_VERIFY_POLL (2),
# WORKER_HEARTBEAT_PROBE (executable printing the heartbeat epoch of the worker name given as
# argument, or `none`; default: backend/venv python -m app.scripts.worker_heartbeat), BACKEND_DIR.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
BACKEND_DIR="${BACKEND_DIR:-$PROJECT_DIR/backend}"
VERIFY_TIMEOUT="${WORKER_VERIFY_TIMEOUT:-45}"
VERIFY_POLL="${WORKER_VERIFY_POLL:-2}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1" >&2; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
err() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

UNITS=(pricing-worker pricing-worker-ml)
HEARTBEATS=(worker worker-ml)
REQUIRED=(yes no)

# Per-worker state, indexed like UNITS.
STATE=()      # pending | ok | skipped | failed
BASELINE=()
LAST_ACTIVE=()
LAST_BEAT=()
PROBLEM_COUNT=0

report_problem() {
  local i=$1 reason=$2
  STATE[$i]=failed
  PROBLEM_COUNT=$((PROBLEM_COUNT + 1))
  err "${UNITS[$i]}: ${reason}"
  echo "PROBLEM ${UNITS[$i]}: ${reason}"
}

# Prints the heartbeat epoch of a worker name (`none` when it never wrote one). Non-zero when it
# cannot be read at all.
heartbeat_of() {
  if [ -n "${WORKER_HEARTBEAT_PROBE:-}" ]; then
    timeout 30 "$WORKER_HEARTBEAT_PROBE" "$1"
  else
    (cd "$BACKEND_DIR" && timeout 30 "$BACKEND_DIR/venv/bin/python" -m app.scripts.worker_heartbeat "$1")
  fi
}

# `advanced NEW OLD`: NEW is a number strictly greater than OLD (OLD may be `none`: any value counts).
advanced() {
  local new=$1 old=$2
  [[ "$new" =~ ^[0-9]+(\.[0-9]+)?$ ]] || return 1
  [ "$old" = none ] && return 0
  awk -v a="$new" -v b="$old" 'BEGIN { exit !(a > b) }'
}

unit_exists() { systemctl cat "$1" >/dev/null 2>&1; }

# 1) Decide, read the baseline heartbeat, restart.
for i in "${!UNITS[@]}"; do
  unit=${UNITS[$i]}
  STATE[$i]=pending
  if ! unit_exists "$unit"; then
    if [ "${REQUIRED[$i]}" = yes ]; then
      report_problem "$i" "la unit no está instalada (ver deploy/systemd/${unit}.service)"
    else
      warn "${unit} no está instalado (ver deploy/systemd/${unit}.service): se omite"
      STATE[$i]=skipped
    fi
    continue
  fi
  if [ "${REQUIRED[$i]}" = no ] && ! systemctl is-enabled --quiet "$unit" 2>/dev/null \
    && ! systemctl is-active --quiet "$unit" 2>/dev/null; then
    warn "${unit} está instalado pero no habilitado ni activo: no se reinicia (el deploy nunca lo habilita)"
    STATE[$i]=skipped
    continue
  fi

  # The baseline is read BEFORE the restart: only a heartbeat newer than it proves the new process.
  if BASELINE[$i]=$(heartbeat_of "${HEARTBEATS[$i]}" 2>/dev/null); then
    :
  else
    BASELINE[$i]=$(date +%s)  # unreadable now: anything older than this moment is not the new process
  fi
  log "Reiniciando ${unit}..."
  if ! sudo systemctl restart "$unit" 2>/dev/null; then
    report_problem "$i" "no se pudo reiniciar (sudo systemctl restart ${unit})"
  fi
done

# 2) Verify every restarted worker within one shared deadline.
deadline=$((SECONDS + VERIFY_TIMEOUT))
while true; do
  pending=0
  for i in "${!UNITS[@]}"; do
    [ "${STATE[$i]}" = pending ] || continue
    unit=${UNITS[$i]}
    if systemctl is-active --quiet "$unit" 2>/dev/null; then LAST_ACTIVE[$i]=yes; else LAST_ACTIVE[$i]=no; fi
    if beat=$(heartbeat_of "${HEARTBEATS[$i]}" 2>/dev/null); then LAST_BEAT[$i]=$beat; else LAST_BEAT[$i]=unreadable; fi
    if [ "${LAST_ACTIVE[$i]}" = yes ] && advanced "${LAST_BEAT[$i]}" "${BASELINE[$i]}"; then
      STATE[$i]=ok
      log "${unit}: activo, heartbeat avanzando (${HEARTBEATS[$i]})"
    else
      pending=1
    fi
  done
  [ "$pending" -eq 0 ] && break
  [ "$SECONDS" -ge "$deadline" ] && break
  sleep "$VERIFY_POLL"
done

for i in "${!UNITS[@]}"; do
  [ "${STATE[$i]}" = pending ] || continue
  unit=${UNITS[$i]}
  if [ "${LAST_ACTIVE[$i]:-no}" != yes ]; then
    report_problem "$i" "no está activo tras el restart (revisar: sudo systemctl status ${unit})"
  elif [ "${LAST_BEAT[$i]:-unreadable}" = unreadable ]; then
    report_problem "$i" "está activo pero no se pudo leer su heartbeat en worker_job_state (${HEARTBEATS[$i]})"
  else
    report_problem "$i" "colgado: el proceso está activo pero su heartbeat (${HEARTBEATS[$i]}) no avanzó en ${VERIFY_TIMEOUT}s"
  fi
done

[ "$PROBLEM_COUNT" -eq 0 ]
