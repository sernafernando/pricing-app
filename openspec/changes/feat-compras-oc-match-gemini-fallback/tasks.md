# Tasks: feat-compras-oc-match-gemini-fallback

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–180 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Config + in-place pool fallback/503 + unit tests + `.env.example` | PR 1 | `pytest tests/unit/test_oc_match_gemini_pool.py` | N/A — no live Gemini; no UI/reclaim | `config.py` + `gemini_pool.py` + unit test + `.env.example` |

## Phase 1: Config

- [x] 1.1 In `backend/app/core/config.py` set `GEMINI_MODEL` default to `gemini-3.5-flash-lite` and add `GEMINI_MODEL_FALLBACK: str = "gemini-3.1-flash-lite"`.
- [x] 1.2 In `backend/.env.example` document `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`, `GEMINI_MODEL`, `GEMINI_MODEL_FALLBACK` with placeholders only (no secret values).

## Phase 2: GeminiPool

- [x] 2.1 In `backend/app/services/oc_match/gemini_pool.py` add optional `fallback_model` on `GeminiPool`; strip empty/same-as-primary to disabled; persist `self.model` / `en_fallback`; `label` = `model=<id> key N/M`.
- [x] 2.2 In `backend/app/services/oc_match/gemini_pool.py` change `load_keys` primary default to `gemini-3.5-flash-lite`; `load_pool` resolves fallback and logs `fallback=disabled` when empty/same.
- [x] 2.3 In `generate_json` (`backend/app/services/oc_match/gemini_pool.py`): default `attempts=12`; 429 adds `cuota_usadas`, rotates unused, no sleep; all keys used → `_cambiar_a_fallback()` once (`i=0`, clear sets) or raise.
- [x] 2.4 In `generate_json` (`backend/app/services/oc_match/gemini_pool.py`): 503 marks `demanda_vistas`, sleeps module constants `(5, 10)` at most twice on the current key, then rotates; all-seen or attempts exhausted → fallback once or raise. Other errors / empty / malformed JSON unchanged.
- [x] 2.5 Raise/log context includes model id; never interpolate key strings. Do not edit `backend/app/services/oc_match/worker.py` (read-only), `extract.py` (read-only), or `match.py` (read-only).

## Phase 3: Unit tests

- [x] 3.1 In `backend/tests/unit/test_oc_match_gemini_pool.py`: 429 on all keys → fallback continues; 429 on fallback or disabled → raise (spec: 429 exhausts / 429 raises).
- [x] 3.2 In `backend/tests/unit/test_oc_match_gemini_pool.py`: 503 calls `time.sleep` with 5 then 10 then rotates; all keys seen 503 → fallback (spec: 503 sleep/rotate / 503 fallback). Patch `time.sleep`.
- [x] 3.3 In `backend/tests/unit/test_oc_match_gemini_pool.py`: empty/same fallback disabled; second `generate_json` stays on fallback after extract switch; `caplog` has `model=` + `key N/M` and omits raw key strings (spec: persist / logs).
- [x] 3.4 Keep existing 429→second-key and malformed-JSON tests green in `backend/tests/unit/test_oc_match_gemini_pool.py`.
