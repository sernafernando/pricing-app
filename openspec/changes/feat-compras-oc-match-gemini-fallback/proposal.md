# Proposal: feat-compras-oc-match-gemini-fallback

## Intent

Live OC-match burns Gemini **429 RPD on one model** and **503 demand on one key** (up to ~7 min sleep per `generate_json`). Need a one-shot fallback model and 503 key rotation instead of the 15×(n+1) ladder.

## Scope

### In Scope
- Default `GEMINI_MODEL` → `gemini-3.5-flash-lite`; add `GEMINI_MODEL_FALLBACK` default `gemini-3.1-flash-lite`.
- In-place `GeminiPool`: 429 key-then-fallback-once; 503 5s/10s then rotate then fallback-once; `attempts=12`.
- Unit tests in `test_oc_match_gemini_pool.py` (no live Gemini).
- Document Gemini vars in `backend/.env.example` (no secret values).
- Delta spec: MODIFY the 3-key pool requirement.
- Single PR.

### Out of Scope
- UI / model picker; reclaim / heartbeat / `progress_phase`; worker, extract, match callers; extra env for sleeps/attempts; live Gemini; malformed-JSON retry.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-oc-match-pipeline`: 3-key pool distinguishes 429 vs 503; one fallback model; log `model=` + key N/M; never log keys.

## Approach

Exploration Approach 1. Keep `load_pool()` and `generate_json(contents, attempts=…)` as the public API. Instance holds the current model so extract→match does not re-enter primary. Same 3 keys on both models. After strip, empty or primary-equal fallback disables. Module constants for sleeps; no new sleep/attempt env.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/core/config.py` | Modified | Default 3.5-flash-lite; add `GEMINI_MODEL_FALLBACK` |
| `backend/app/services/oc_match/gemini_pool.py` | Modified | Fallback resolve, 429/503 policy, labels |
| `backend/tests/unit/test_oc_match_gemini_pool.py` | Modified | 429/503/fallback/log cases |
| `backend/.env.example` | Modified | Document Gemini vars (placeholders only) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| 3.1 quality drift vs 3.5 on Pricing prompts | Med | Fallback last resort; acta review already exists |
| Coolify sets fallback equal to primary | Low | Treat as disabled; log `fallback=disabled` |
| 503 classifier miss (`code==503` / `UNAVAILABLE`) | Low | Leave classifier as-is unless prod shows a new shape |
| 12×2 attempts burn both models in an outage | Med | Accept vs today’s 14 min stall + single-model RPD |

## Rollback Plan

Revert the four files. Restore Coolify `GEMINI_MODEL` if operators changed it. No migration.

## Dependencies

- Parent `feat-compras-oc-match` (PR #1304). Sibling ops-ux 45m reclaim stays. Same 3 Gmail-account keys.

## Success Criteria

- [ ] Primary default `gemini-3.5-flash-lite`; fallback default `gemini-3.1-flash-lite`; empty/same disables.
- [ ] 429 rotates keys then fallback once; no 429 sleep; already-fallback/disabled raises.
- [ ] 503 ≤2 sleeps (5s, 10s) then rotate; all-seen or attempts exhausted → fallback once.
- [ ] Logs show `model=` + key N/M; never key material. `generate_json` default attempts=12.
- [ ] `worker.py` / `extract.py` / `match.py` unchanged; unit tests mock the SDK.
