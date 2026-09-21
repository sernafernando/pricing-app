# Exploration: feat-compras-oc-match-gemini-fallback

Follow-up to `feat-compras-oc-match` (PR #1304). Live OC-match burns Gemini **429 RPD on one model** and **503 demand on one key** (up to ~7 min sleep per `generate_json`). Gabe locked: primary `gemini-3.5-flash-lite`, one-shot fallback to `gemini-3.1-flash-lite` (validated on Automations), three Gmail-account keys (separate RPD per model per account), and a 503 policy that rotates keys instead of sleeping 8 times on one key.

Parent/ops-ux locks stay: two short worker sessions, **no Session during Gemini**, no pool heartbeat, reclaim 45m on `started_at`, mail OFF, UI/poll unchanged.

---

## Exploration: Gemini model fallback + 503 key rotation

### Current State

`GeminiPool` (`backend/app/services/oc_match/gemini_pool.py`) loads `GEMINI_API_KEY` / `_2` / `_3` (deduped, `#` comments skipped) and a **single** `settings.GEMINI_MODEL` whose code default is still **`gemini-3.6-flash`**. `load_pool()` is called once per job in `worker.process_oc_match_job`; that instance serves **two** `generate_json` calls (`extract_one`, then batched `match_renglones`).

**429 / cuota:** rotate to a key not yet in `cuota_usadas`. When every key has 429'd, **raise** — no second model. No sleep.

**503 / demanda:** if `n < attempts - 1` (default `attempts=8`), **stay on the same key** and `time.sleep(15 * (n + 1))` → 15+30+45+60+75+90+105 = **420s** per call. Two calls ≈ **14 min** idle. This is why `feat-compras-oc-match-ops-ux` raised reclaim to 45m and left `gemini_pool.py` read-only.

**Logging:** `key {i+1}/{n}` only. Keys are never logged (keep). Model name is not in retry/rotate lines.

**Tests:** `test_oc_match_gemini_pool.py` covers 429→second key and malformed JSON. No 503, no all-keys-exhausted, no fallback, no log-secret assertions.

**Config:** `GEMINI_MODEL` exists; **no** `GEMINI_MODEL_FALLBACK`. `backend/.env.example` does not document Gemini vars (Coolify `.env` is the live store).

**Spec:** `compras-oc-match-pipeline` requires a 3-key pool that “rotates on 429/503” but does not distinguish cuota vs demanda and does not mention a second model.

### Affected Areas

- `backend/app/core/config.py` — default `GEMINI_MODEL` → `gemini-3.5-flash-lite`; add `GEMINI_MODEL_FALLBACK` default `gemini-3.1-flash-lite`.
- `backend/app/services/oc_match/gemini_pool.py` — fallback resolve, cuota→model switch once, 503 short sleeps + key rotate, attempt cap, model+key labels in logs.
- `backend/tests/unit/test_oc_match_gemini_pool.py` — 429 all-keys→fallback; 429 on fallback/no-fallback→raise; 503 ≤2 sleeps then rotate; 503 all-keys→fallback; empty/same fallback disabled; logs omit secrets.
- `backend/.env.example` — document `GEMINI_MODEL`, `GEMINI_MODEL_FALLBACK`, three keys (no secret values).
- `openspec/changes/feat-compras-oc-match/specs/compras-oc-match-pipeline/spec.md` (and/or a delta under this change) — **MODIFY** the 3-key requirement for model fallback + 503 policy.
- `backend/app/services/oc_match/worker.py`, `extract.py`, `match.py` — **unchanged** if `generate_json(contents, attempts=…)` and `load_pool()` stay the public API.
- Reclaim / UI / `progress_phase` — **out of scope** (ops-ux). Shorter 503 sleeps make 45m reclaim conservative, not wrong.

### Approaches

1. **In-place `GeminiPool` (model + key state on the instance)** — extend the existing class: primary/fallback fields, `cuota_usadas` / `demanda_vistas` per current model, `_cambiar_a_fallback()` once, retune 503.
   - Pros: extract/match/worker stay callers; one pool per job already matches “switch once and keep going”; tests already target this class; smallest diff.
   - Cons: `generate_json` loop gets a bit denser (still one function).
   - Effort: **Low**

2. **Orchestrator outside the pool (two `GeminiPool`s)** — first pool raises a typed `CuotaAgotada` / `DemandaAgotada`; worker/wrapper builds a second pool with the fallback model.
   - Pros: each pool stays “one model”.
   - Cons: worker/extract/match must learn the wrapper; two `generate_json` calls would re-enter primary after extract already exhausted it unless the wrapper is job-scoped anyway — same state, more seams.
   - Effort: **Medium** (wrong seam)

3. **Env-only default change (`GEMINI_MODEL=gemini-3.5-flash-lite`), keep today’s 503/429 loop**
   - Pros: one-line Coolify/config change.
   - Cons: does not use the second RPD bucket; still burns 8 long sleeps on one key; 429 still dies after 3 keys on one model.
   - Effort: **Low** (insufficient)

### Recommendation

**Approach 1.** Keep the pool as the only rotation brain. Locked constants (Gabe + exploration close):

| Item | Decision |
|------|----------|
| Primary | `GEMINI_MODEL`, code default **`gemini-3.5-flash-lite`** (was `gemini-3.6-flash`). Coolify will set the same. |
| Fallback | `GEMINI_MODEL_FALLBACK`, code default **`gemini-3.1-flash-lite`**. After strip, **empty or equal to primary disables** fallback. |
| Keys | Same 3 Gmail-account keys on both models (RPD is per model per account). Dedupe/`#` skip unchanged. |
| 429 / cuota | Rotate keys on the **current** model; track `cuota_usadas`. When **all** keys are in that set → switch to fallback **once**, reset `i` to 0, clear cuota/demanda sets, continue. If already on fallback or fallback disabled → raise. No sleep on 429. |
| 503 / demanda | Do **not** run the 15×(n+1) ladder. On current key: at most **2 short sleeps** (`5s`, then `10s` — module constants, not new env), then rotate. Mark a key “seen 503” on first 503. When **every** key has been seen **or** the attempt budget is exhausted → fallback once (same reset as cuota). If already on fallback / no fallback → raise. |
| Attempt cap | **`attempts=12`** default on `generate_json` (was 8). Cap is **per call**, across both models. Extract and match each get their own 12. |
| Instance model | Fallback switch is **pool-instance state**. If extract already moved to 3.1, match stays on 3.1 (do not re-burn primary RPD). |
| Logging | Never log key material. Every rotate/retry/switch line: `model=<id> key N/M`. |
| Non-goals | No UI/model picker; no reclaim/heartbeat change; no retry on malformed JSON/empty text; no extra env for sleeps/attempts; no live Gemini in tests. |

**Worst-case sleep after this change:** ≤ 2 sleeps × 3 keys × 2 models × 15s = **90s** of sleep per `generate_json` (usually less because “all keys seen 503” can switch before burning 2 sleeps on the last key). Two calls ≪ 45m reclaim.

**Spec impact:** MODIFY “Async extract with 3-key Gemini pool” — rotate keys on 429; 503 is short-sleep-then-rotate; one fallback model when the current model is exhausted; log model + key N/M.

**PR:** single PR, well under 400 authored lines. No migration.

### Risks

- **3.1 quality drift vs 3.5 on Pricing prompts** — Automations validated large-OC parity and a small Windows SKU; Pricing prompts are a port, not byte-identical. Mitigation: fallback is last resort; acta/operator review already exists for weak matches. No live A/B in this change.
- **Fallback equals primary in Coolify by mistake** — treated as disabled; job fails after one model’s keys. Mitigation: `load_pool` logs `fallback=disabled` when empty/same.
- **503 classifier miss** — only `code==503` or `"UNAVAILABLE"` in `str(exc)` (today). Other 5xx still raise. Leave as-is unless production shows a new shape.
- **12 attempts × 2 calls** still spend RPD on both models during a prolonged outage. Acceptable vs today’s 14 min stall + single-model RPD burn.
- **Exception text in `job.error_message`** — must keep using SDK messages without interpolating key strings (already true). Prefer including **model id** in raise/log context for ops.

### Open Questions

None. Sleep pair `5s/10s` and cap `12` sit inside Gabe’s “short / ~10–12” lock; propose may copy them as constants.

### Ready for Proposal

**Yes.** Orchestrator should tell the user: product decisions are locked; recommended seam is in-place `GeminiPool`; next phase is `sdd-propose`. No production code in this phase.
