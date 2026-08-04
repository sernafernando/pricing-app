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
| `backend/app/api/endpoints/productos_listing.py` (`con_promo_aplicada` block) | `fetch_mlas_with_started()` is type-agnostic and returns an unbounded set of every `started`-promo MLA, folded into an unbounded `IN(...)`. Measured **2942** `started` MLAs in prod (2026-07-20), well under Postgres' ~65535 bind-param ceiling — theoretical at current scale | If the `started` set approaches the bind-param ceiling: bound the cross-DB query to the page / known-local MLAs instead of fetching the universe | 2026-07-20 |
| `backend/app/api/endpoints/productos_colors.py` (`_dual_write_legacy`) | PR2→PR3 transitional dual-write: writes to the new per-team `producto_color` table (U layer) are mirrored back into legacy `productos_pricing.color_marcado[_tienda]`, kept only as a rollback safety net during the teams-color migration | Remove once the `producto_color` migration is verified stable in prod for a full release cycle with no rollback needed | 2026-07-20 |
| `backend/app/routers/consultas.py:1471` (PM dropdown query) | sub-pm-scope-marcas PR1 unified only the read scope (`scope_exists_sql` over `marcas_pm ∪ marca_sub_pm`); the PM dropdown stays titular-only because the `pm=` name filter joins (`get_ranking`/`resumen`/`kpis`/`facets`) still resolve via `marcas_pm` alone — unifying only the dropdown would let a selected sub-PM return zero rows silently | PR2 unifies the dropdown source AND the pm-name filter joins over `marca_sub_pm` together (guarded by `test_facets_pm_dropdown_stays_titular_only` until then) | 2026-07-24 |
| `frontend/src/test/visual/globalOverrides.visual.test.jsx` (the `it.fails` block) | `theme.css:197-244` styles `select, option` and `input[type="text"\|"number"\|"email"\|"password"], textarea` globally with `!important`, at a specificity that beats `forms-tesla.css`. On a real control the primitive contributes almost nothing: padding, radius, font-size, colours and the focus ring all come from `theme.css`, `inputSm` is inert, and `:disabled` is not painted at all. Pinned with `it.fails` rather than fixed — deleting those global rules would restyle the ~56 modules still relying on them | The forms-tesla migration retires `theme.css`'s global form rules; then promote each `it.fails` to a normal assertion | 2026-08-04 |
| `frontend/src/test/visual/formsPrimitive.visual.test.jsx` (dark-mode disabled-text `it.fails`) | `--cf-text-muted` is `rgba(255, 255, 255, 0.4)` in the dark block of `design-tokens.css`; composited over the `--cf-bg-app` (#000000) disabled fill it reaches the eye as `rgb(102, 102, 102)` = **3.66:1**, under the 4.5:1 this suite asserts everywhere else. Surfaced by fixing `contrastRatio()`, which had been discarding the alpha channel and scoring the pair as opaque white on black = 21:1, the theoretical maximum. Pinned with `it.fails` rather than fixed — retuning the token repaints every muted/placeholder/disabled surface in the app | A designer decides the bar: either raise `--cf-text-muted` (dark) to clear 4.5:1, or document the WCAG 1.4.3 inactive-control exemption in `frontend/AGENTS.md` and lower this assertion deliberately. Then promote the `it.fails` | 2026-08-04 |

## Resolved

| File:Line | Shortcut | Resolved |
|-----------|----------|----------|
| `backend/app/api/endpoints/offsets_ganancia/_consumo_individual.py:58` (`obtener_resumen_offsets_individuales`) | Per-offset `OffsetIndividualResumen.filter(offset_id == x).first()` inside a loop over `offsets_con_limites` — the 11th N+1 site found during `dashboard-batch-prefetch` PR1 adversarial review | 2026-07-03 (PR2 of `dashboard-batch-prefetch`, Task 4 — batched via `fetch_resumenes_individuales`) |
| `backend/app/routers/administracion_compras.py` (wipe-compras route decorator) | Env-gate dependency only ran after the HTTP method matched, so `GET /testing/wipe-compras` outside dev/testing returned 405 instead of 404 — revealed the route exists via method-probing | 2026-07-16 — moot: the env-gate itself was removed (it contradicted the 2026-06-10 decision keeping the endpoint reachable in production). The route no longer hides, so there is nothing to leak; the `administracion.wipe_compras_testing` permission is the guard |
