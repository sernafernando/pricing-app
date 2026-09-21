# Design: feat-compras-oc-match-gemini-fallback

## Technical Approach

Extend in-place `GeminiPool` (exploration Approach 1). `load_pool()` and `generate_json(contents, attempts=…)` stay the public API so `worker.py` / `extract.py` / `match.py` stay callers. Spec: MODIFY `compras-oc-match-pipeline` 3-key pool.

## Architecture Decisions

| Option | Tradeoff | Decision |
|--------|----------|----------|
| In-place pool vs two pools / worker wrapper | Wrapper re-enters primary after extract unless job-scoped anyway | **In-place.** Instance `model` + `en_fallback`. |
| Env-only `GEMINI_MODEL` change | Misses second RPD bucket; keeps 8 long 503 sleeps | **Rejected.** |
| Fallback env empty/same | Coolify can copy-paste the same id | **Disabled.** `load_pool` logs `fallback=disabled`. |
| 503 15×(n+1) vs 5s/10s then rotate | 420s/call vs ≤90s worst-case sleep | **`(5, 10)` module constants.** No new env. |
| `attempts` 8 vs 12 | 12 covers 3 keys × 2 models × short 503 | **Default 12 per `generate_json`.** |
| `cuota_usadas` local vs instance | Local already resets per call; model must persist | **Sets local to the call; `model` on the instance.** On fallback: `i=0`, clear both sets. |
| 503 classifier | Other 5xx still raise | **Keep `code==503` or `"UNAVAILABLE"` in `str(exc)`.** |

## Data Flow

```
load_pool() → keys + primary + optional fallback
generate_json (attempts=12, per call):
  try generate_content(model=self.model)
  429 → cuota_usadas.add(i); rotate unused; all used → _cambiar_a_fallback() or raise
  503 → demanda_vistas.add(i); sleep 5s then 10s on same key; then rotate
        all seen or n exhausted → _cambiar_a_fallback() or raise
  other / bad JSON / empty text → raise (unchanged)
extract_one → match_renglones share one pool; if extract fell back, match stays on 3.1
```

`_cambiar_a_fallback()`: set `self.model` to fallback, `en_fallback=True`, `i=0`, new `Client`, clear cuota/demanda. Call at most once.

503 early-exit: first 503 on the last unseen key marks all seen → fallback without burning the second sleep on that key. Worst-case still ≤ 2×3×2×15s = 90s sleep per call.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/core/config.py` | Modify | `GEMINI_MODEL` default `gemini-3.5-flash-lite`; add `GEMINI_MODEL_FALLBACK` default `gemini-3.1-flash-lite`. |
| `backend/app/services/oc_match/gemini_pool.py` | Modify | Fallback resolve; 429/503 policy; `attempts=12`; `label` = `model=<id> key N/M`; raise/log include model id, never keys. |
| `backend/tests/unit/test_oc_match_gemini_pool.py` | Modify | Cases below; `patch` `time.sleep` and `genai.Client`. |
| `backend/.env.example` | Modify | Comment-document the three keys + both model vars (placeholders, no secrets). |

Unchanged: `worker.py`, `extract.py`, `match.py`, reclaim, UI.

## Interfaces / Contracts

```python
DEMANDA_SLEEPS: tuple[int, int] = (5, 10)
# GeminiPool(keys, model, fallback_model: str | None = None)
# fallback_model None / "" / == model → disabled (existing 2-arg tests stay valid)
def load_pool() -> GeminiPool: ...
def generate_json(self, contents: object, attempts: int = 12) -> dict[str, Any]: ...
```

`load_keys()` keeps returning `(keys, primary)` with default strip fallback `gemini-3.5-flash-lite`. `load_pool()` reads `GEMINI_MODEL_FALLBACK`, strips, disables if empty/same, constructs `GeminiPool(keys, model, fallback)`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit | 429 all keys → fallback; 429 on fallback/disabled → raise | Mock `ClientError(429)` per client |
| Unit | 503 ≤2 `sleep(5)`/`sleep(10)` then rotate; all-seen → fallback | `patch` `time.sleep`; `ServerError(503)` |
| Unit | empty/same fallback disabled; instance model persists across two `generate_json` | Construct pool; assert `pool.model` |
| Unit | logs omit key strings; include model + `key N/M` | `caplog` |
| Unit | existing 429→second key + malformed JSON | Keep current tests |
| Integration / E2E / live Gemini | — | **Out of scope** |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. Gemini stays HTTPS SDK; keys stay in Settings and must never appear in logs or `error_message` interpolation.

## Migration / Rollout

No migration. Coolify should set `GEMINI_MODEL=gemini-3.5-flash-lite` and `GEMINI_MODEL_FALLBACK=gemini-3.1-flash-lite` (code defaults match). Single PR. Revert the four files to roll back.

## Open Questions

- None. Locked in `state.yaml` / exploration.
