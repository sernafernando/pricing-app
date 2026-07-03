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
| `backend/app/routers/administracion_compras.py` (wipe-compras route decorator) | Env-gate dependency only runs after the HTTP method matches, so `GET /testing/wipe-compras` outside dev/testing returns 405 instead of 404 — reveals the route exists via method-probing | If the route is moved to conditional registration (only mounted when `settings.is_dev_or_test`) | 2026-07-02 |

## Resolved

| File:Line | Shortcut | Resolved |
|-----------|----------|----------|
| `backend/app/api/endpoints/offsets_ganancia/_consumo_individual.py:58` (`obtener_resumen_offsets_individuales`) | Per-offset `OffsetIndividualResumen.filter(offset_id == x).first()` inside a loop over `offsets_con_limites` — the 11th N+1 site found during `dashboard-batch-prefetch` PR1 adversarial review | 2026-07-03 (PR2 of `dashboard-batch-prefetch`, Task 4 — batched via `fetch_resumenes_individuales`) |
