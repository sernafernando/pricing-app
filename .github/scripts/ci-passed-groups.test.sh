#!/usr/bin/env bash
# Scenario tests for ci-passed-groups.sh with a stubbed `gh`: no network,
# no token. Run: bash .github/scripts/ci-passed-groups.test.sh
#
# The stub serves one earlier run (head P, PR #7) whose backend and frontend
# jobs all succeeded, plus a compare result built from FAKE_STATUS and
# FAKE_FILES (newline-separated paths). It applies the script's own `--jq`
# filter with jq, so the filters are exercised for real.

set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
script="$here/ci-passed-groups.sh"
stub="$(mktemp -d)"
trap 'rm -rf "${stub:?}"' EXIT

cat >"$stub/gh" <<'STUB'
#!/usr/bin/env bash
path="" filter="."
while [ $# -gt 0 ]; do
  case "$1" in
    --jq) filter="$2"; shift 2 ;;
    -X | -f) shift 2 ;;
    repos/*) path="$1"; shift ;;
    *) shift ;;
  esac
done
[ "${FAKE_API_FAIL:-}" = "1" ] && exit 1
case "$path" in
  */workflows/*/runs*)
    json='{"workflow_runs":[{"id":101,"head_sha":"P","pull_requests":[{"number":7}],"head_repository":{"full_name":"o/r"}}]}' ;;
  */runs/101/jobs*)
    json='{"jobs":[{"name":"Backend Lint","conclusion":"success"},{"name":"Backend Tests","conclusion":"success"},{"name":"Backend Tests (Postgres)","conclusion":"success"},{"name":"Backend Tests (Postgres volume)","conclusion":"success"},{"name":"Frontend Lint","conclusion":"success"},{"name":"Frontend Build","conclusion":"success"},{"name":"Frontend Tests","conclusion":"success"},{"name":"Frontend Visual Tests","conclusion":"success"}]}' ;;
  */compare/*)
    json="$(jq -n --arg s "$FAKE_STATUS" --arg f "$FAKE_FILES" \
      '{status: $s, files: ($f | split("\n") | map(select(. != "") | {filename: .}))}')" ;;
  *) exit 1 ;;
esac
jq -r "$filter" <<<"$json"
STUB
chmod +x "$stub/gh"

fails=0
# check <name> <status> <files> <expected skip_backend> <expected skip_frontend>
check() {
  local out want
  out="$(PATH="$stub:$PATH" FAKE_STATUS="$2" FAKE_FILES="$3" \
    REPO=o/r PR_NUMBER=7 HEAD_SHA=H HEAD_REF=b HEAD_REPO=o/r WORKFLOW_ID=1 \
    bash "$script" 2>/dev/null | tr '\n' ' ')"
  want="skip_backend=$4 skip_frontend=$5 "
  if [ "$out" = "$want" ]; then
    echo "ok   $1"
  else
    echo "FAIL $1: got '$out', want '$want'"
    fails=$((fails + 1))
  fi
}

check "frontend-only fix skips backend" ahead "frontend/src/a.ts" true false
check "backend-only fix skips frontend" ahead "backend/app/a.py" false true
check "ci.yml change skips neither group" ahead ".github/workflows/ci.yml" false false
check "root file change skips neither group" ahead "README.md" false false
check "backend + shared path skips neither group" ahead $'backend/app/a.py\n.github/scripts/x.sh' false false
check "rename into frontend/ from backend/ counts for both" ahead $'backend/a.py\nfrontend/a.py' false false
check "force-push or rebase (diverged) skips nothing" diverged "frontend/src/a.ts" false false
check "same head (identical) skips both" identical "" true true
FAKE_API_FAIL=1 check "API error skips nothing" ahead "frontend/src/a.ts" false false

if [ "$fails" -ne 0 ]; then
  echo "$fails scenario(s) failed"
  exit 1
fi
echo "all scenarios passed"
