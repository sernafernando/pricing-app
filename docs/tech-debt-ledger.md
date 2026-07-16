# Technical Debt Ledger

Deliberate shortcuts marked with `ponytail:` in the codebase, harvested here so "later" doesn't become "never".

## How it works

1. When you take a conscious shortcut, leave a marker at that exact line:
   `# ponytail: <what was deferred and the condition to revisit>`
2. Harvest markers on demand:
   ```bash
   rg -n "ponytail:" --glob '!docs/tech-debt-ledger.md' backend frontend
   ```
3. Move each item into the **Open debt** table below, then resolve them before releases.

## Open debt

| File:Line | Shortcut | Revisit when | Added |
|-----------|----------|--------------|-------|
| `backend/app/api/endpoints/auth.py` (`login` route) | Malformed-body (422) login requests bypass the rate limiter — FastAPI validates the request body before the slowapi-wrapped endpoint runs, so an attacker sending unparseable bodies is never counted | If login abuse via malformed bodies is observed (would need a middleware-level limiter that runs before body validation) | 2026-07-03 |
| `backend/app/services/ml_questions/ingestion_service.py` (cursor persistence) | Cursor tracking uses `NULL`/`''` interchangeably in one ingestion path — low-risk collision, not unified | If a cursor-position bug is ever traced to this ambiguity | 2026-07-06 |
| `backend/app/services/ml_questions/` (account scope) | Single ML account per environment — no multi-account support | If a second ML account needs the bot in the same environment | 2026-07-06 |
| `backend/app/routers/ml_bot.py` (bot status read) | No standalone `GET /toggle-status`; reading bot on/off requires `ml_bot.config` in addition to `ml_bot.on_off` | If a role needs to read bot status without full config access | 2026-07-06 |
| `frontend/src/pages/MLQuestions.jsx` (status filter) | Panel status filter accepts a single value only (no multi-status/OR filter) | If operators need to view multiple statuses at once without backend multi-status support | 2026-07-06 |
| `backend/app/services/ml_questions/policy.py` (denylist on manual edits) | Soft denylist warning on manual edits is advisory only — does not block human-authored content, by design | Revisit only if this design decision is reversed | 2026-07-06 |

## Resolved

| File:Line | Shortcut | Resolved |
|-----------|----------|----------|
| `backend/app/api/endpoints/offsets_ganancia/_consumo_individual.py:58` (`obtener_resumen_offsets_individuales`) | Per-offset `OffsetIndividualResumen.filter(offset_id == x).first()` inside a loop over `offsets_con_limites` — the 11th N+1 site found during `dashboard-batch-prefetch` PR1 adversarial review | 2026-07-03 (PR2 of `dashboard-batch-prefetch`, Task 4 — batched via `fetch_resumenes_individuales`) |
| `backend/app/routers/administracion_compras.py` (wipe-compras route decorator) | Env-gate dependency only ran after the HTTP method matched, so `GET /testing/wipe-compras` outside dev/testing returned 405 instead of 404 — revealed the route exists via method-probing | 2026-07-16 — moot: the env-gate itself was removed (it contradicted the 2026-06-10 decision keeping the endpoint reachable in production). The route no longer hides, so there is nothing to leak; the `administracion.wipe_compras_testing` permission is the guard |
