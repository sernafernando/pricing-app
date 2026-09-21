# Apply progress: feat-compras-oc-match-gemini-fallback

**Change**: feat-compras-oc-match-gemini-fallback
**Mode**: Standard
**Delivery**: single-pr, Low risk
**Token**: sha256:87adcd21847a3d08251543ec305fad236805fbb4db7c8be1a6e6cf99fc7ba08e

## Completed Tasks

- [x] 1.1 Config: `GEMINI_MODEL` default `gemini-3.5-flash-lite`; add `GEMINI_MODEL_FALLBACK` default `gemini-3.1-flash-lite`
- [x] 1.2 `.env.example` documents three keys + both model vars (placeholders only)
- [x] 2.1 `GeminiPool(keys, model, fallback_model=None)`; empty/same disables; persist `model` / `en_fallback`; `label` = `model=<id> key N/M`
- [x] 2.2 `load_keys` primary default `gemini-3.5-flash-lite`; `load_pool` resolves fallback and logs `fallback=disabled` when disabled
- [x] 2.3 `generate_json` default `attempts=12`; 429 rotates unused (no sleep); all keys → `_cambiar_a_fallback()` once or raise
- [x] 2.4 503: `DEMANDA_SLEEPS=(5, 10)` max twice per key then rotate; all-seen or budget exhausted → fallback once or raise
- [x] 2.5 Raise/log includes model id; never interpolates key strings; worker/extract/match untouched
- [x] 3.1 429 all keys → fallback; 429 on fallback or disabled → raise
- [x] 3.2 503 sleeps 5 then 10 then rotates; all keys seen → fallback (`time.sleep` patched)
- [x] 3.3 empty/same disabled; second `generate_json` stays on fallback; caplog has `model=` + `key N/M`, omits secrets
- [x] 3.4 Existing 429→second-key and malformed-JSON tests remain green

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db SECRET_KEY=ci-test-secret-key-minimum-32-bytes! ERP_BASE_URL=http://localhost:9 RATE_LIMIT_STORAGE_URI=memory:// ./venv/bin/python -m pytest tests/unit/test_oc_match_gemini_pool.py -q --tb=short` → exit 0, **13 passed**, 3 warnings (pre-existing Starlette deprecations) |
| Runtime harness command/scenario and exact result | N/A — no live Gemini; no UI/reclaim; unit mocks of `genai.Client` and `time.sleep` only (design: integration/E2E out of scope) |
| Rollback boundary | `backend/app/core/config.py` + `backend/app/services/oc_match/gemini_pool.py` + `backend/tests/unit/test_oc_match_gemini_pool.py` + `backend/.env.example` — revert these four files; `worker.py` / `extract.py` / `match.py` were not edited |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `backend/app/core/config.py` | Modified | Primary default 3.5-flash-lite; add `GEMINI_MODEL_FALLBACK` |
| `backend/.env.example` | Modified | Document three Gemini keys + both model vars (placeholders) |
| `backend/app/services/oc_match/gemini_pool.py` | Modified | In-place fallback, 429/503 policy, attempts=12, labels |
| `backend/tests/unit/test_oc_match_gemini_pool.py` | Modified | 429/503/fallback/persist/log cases; keep existing tests |

## Deviations from Design

None — implementation matches design.

## Issues Found

None.

## Remaining Tasks

None. 11/11 tasks complete.

## Workload / PR Boundary

- Mode: single PR
- Current work unit: 1 (config + in-place pool fallback/503 + unit tests + `.env.example`)
- Boundary: starts at config defaults; ends at unit-tested pool + env docs
- Estimated review budget impact: 294 insertions / 31 deletions (~325 authored lines), under 400

## Status

11/11 tasks complete. Ready for verify.
