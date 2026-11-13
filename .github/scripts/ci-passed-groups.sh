#!/usr/bin/env bash
# Decides which CI job groups a pull request run may skip because an earlier
# run of the SAME pull request already passed them and nothing in their area
# changed since. Used by the `changes` job in .github/workflows/ci.yml.
#
# A group is skipped only when BOTH hold:
#   (a) an earlier completed run of this workflow for this PR passed EVERY
#       job of the group, at PR head commit P;
#   (b) P is an ancestor of the current PR head (no force-push or rebase in
#       between) and the files changed from P to the current head are all
#       outside the group's area. Area: backend = `backend/` plus shared
#       paths, frontend = `frontend/` plus shared paths. Shared = anything
#       outside both (`.github/` workflows and scripts, root files, `scripts/`,
#       docs): a CI-config or root change re-runs BOTH groups.
#
# Fail safe: the script always prints `skip_backend=false` and
# `skip_frontend=false` unless it PROVED a skip. Any API error, missing run,
# unknown commit or oversized diff leaves the group running. It never exits
# non-zero on purpose: a broken detection must cost minutes, never a skipped
# check.
#
# Env: GH_TOKEN (needs `actions: read`, `contents: read`), REPO (owner/name),
# PR_NUMBER, HEAD_SHA (PR head, not the merge commit), HEAD_REF and
# HEAD_REPO (the PR's head branch and its owner/name), WORKFLOW_ID.
# Runs locally too: `REPO=... PR_NUMBER=... HEAD_SHA=... HEAD_REF=...
# HEAD_REPO=... WORKFLOW_ID=ci.yml
# .github/scripts/ci-passed-groups.sh` with an authenticated `gh`.

set -uo pipefail

# Must match the `name:` of the jobs in ci.yml. A renamed job never matches,
# so its group never skips (fail safe, but it silently stops saving minutes).
BACKEND_JOBS='["Backend Lint","Backend Tests","Backend Tests (Postgres)","Backend Tests (Postgres volume)"]'
FRONTEND_JOBS='["Frontend Lint","Frontend Build","Frontend Tests","Frontend Visual Tests"]'

# Earlier runs inspected, newest first. Bounds the API calls per run.
MAX_RUNS=20
# The compare API lists at most 300 files. At that size the list may be
# truncated, so "no backend file" cannot be trusted.
MAX_FILES=300

skip_backend=false
skip_frontend=false
emit() {
  echo "skip_backend=$skip_backend"
  echo "skip_frontend=$skip_frontend"
}
trap emit EXIT

for var in REPO PR_NUMBER HEAD_SHA HEAD_REF HEAD_REPO WORKFLOW_ID; do
  if [ -z "${!var:-}" ]; then
    echo "::notice::incremental CI: $var is empty, running every group" >&2
    exit 0
  fi
done

# Prints the PR head SHA of the newest earlier run (of the latest $MAX_RUNS
# completed ones for this PR) whose jobs in group $1 all succeeded.
# `filter=latest` takes the last attempt of each job, so a failed job that
# was re-run green counts as green.
passed_at() {
  local want="$1" id sha ok
  while IFS=$'\t' read -r id sha; do
    [ -n "$id" ] || continue
    ok="$(gh api "repos/$REPO/actions/runs/$id/jobs?filter=latest&per_page=100" \
      --jq "[.jobs[] | select(.conclusion == \"success\") | .name] as \$ok
            | $want | all(. as \$n | \$ok | index(\$n) != null)")" || return 1
    if [ "$ok" = "true" ]; then
      echo "$sha"
      return 0
    fi
  done <<<"$RUNS"
  return 1
}

# Prints the files changed from $1 to HEAD_SHA, both sides of a rename.
# Fails (prints nothing) unless $1 is an ancestor of HEAD_SHA and the list is
# complete.
changed_since() {
  local p="$1" out status count
  out="$(gh api "repos/$REPO/compare/$p...$HEAD_SHA" \
    --jq '.status, (.files | length), (.files[] | .filename, (.previous_filename // empty))')" || return 1
  status="$(sed -n 1p <<<"$out")"
  count="$(sed -n 2p <<<"$out")"
  # `ahead`/`identical`: P is an ancestor of the head. `diverged`/`behind`
  # mean a force-push or rebase, which can bring in new main code.
  case "$status" in ahead | identical) ;; *) return 1 ;; esac
  [ "$count" -lt "$MAX_FILES" ] || return 1
  sed -n '3,$p' <<<"$out"
}

# Completed pull_request runs of this workflow for this PR, newest first.
# The current run is still in progress, so it is not in the list. Filtered
# by head branch on the API side: unfiltered, 100 runs cover about one day
# of this repo and a PR's earlier green run falls out of the window.
# A run belongs to this PR when its `pull_requests` lists it. For a PR from
# a fork that list is always empty, so there the run's head repository and
# branch identify it instead. Same-repo runs with an empty list (an older,
# merged PR that reused the branch name) never count.
RUNS="$(gh api -X GET "repos/$REPO/actions/workflows/$WORKFLOW_ID/runs" \
  -f event=pull_request -f status=completed -f per_page=100 -f branch="$HEAD_REF" \
  --jq "[.workflow_runs[]
         | select(any(.pull_requests[]; .number == $PR_NUMBER)
                  or (.pull_requests == [] and env.HEAD_REPO != env.REPO
                      and .head_repository.full_name == env.HEAD_REPO))
        ][:$MAX_RUNS][] | [.id, .head_sha] | @tsv")" || {
  echo "::notice::incremental CI: could not list earlier runs, running every group" >&2
  exit 0
}
if [ -z "$RUNS" ]; then
  echo "incremental CI: no earlier completed run of PR #$PR_NUMBER, running every group" >&2
  exit 0
fi

# Here-strings, not `printf | grep -q`: under pipefail an early `grep -q`
# exit kills printf with SIGPIPE, and the result would flip.
if p="$(passed_at "$BACKEND_JOBS")" && files="$(changed_since "$p")"; then
  if ! grep -qv -e '^frontend/' -e '^$' <<<"$files"; then
    echo "incremental CI: backend passed at $p, nothing outside frontend/ changed since" >&2
    skip_backend=true
  fi
fi
if p="$(passed_at "$FRONTEND_JOBS")" && files="$(changed_since "$p")"; then
  if ! grep -qv -e '^backend/' -e '^$' <<<"$files"; then
    echo "incremental CI: frontend passed at $p, nothing outside backend/ changed since" >&2
    skip_frontend=true
  fi
fi
