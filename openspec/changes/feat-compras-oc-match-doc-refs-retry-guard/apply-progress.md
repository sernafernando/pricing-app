# Apply Progress: feat-compras-oc-match-doc-refs-retry-guard

**Change**: feat-compras-oc-match-doc-refs-retry-guard
**Mode**: Standard
**Branch**: `feat/compras-oc-match-doc-refs-retry-guard` stacked on `origin/feat/compras-oc-match-pedido-doc-refs` (`5c83d6bb`, PR #1314)
**Alembic parent**: `compras_042_pedido_doc_refs` (`compras_043` hangs off it)

## Completed Tasks

- [x] 1.1 Branch already existed on `origin/feat/compras-oc-match-pedido-doc-refs`; did not recreate or switch to ean-extract-fallback
- [x] 2.1 `OcMatchJob.doc_refs_aplicado_at` DateTime TZ NULL after `finished_at`; no index
- [x] 2.2 Alembic `compras_043_oc_match_doc_refs_aplicado` off `compras_042_pedido_doc_refs`
- [x] 2.3 `Field(None, max_length=500)` on Base / Update / Correccion; `numero_factura` stays 50; Text unchanged
- [x] 2.4 `OcMatchRetryRequest.refrescar_doc_refs: bool = False`; stamp not on `OcMatchJobResponse`
- [x] 3.1 `apply_writeback(...) -> bool` True iff routeable + ≥1 token
- [x] 3.2 Worker skips write-back when stamp set; stamps `datetime.now(UTC)` only after True; flush so the same session sees it
- [x] 3.3 `queue_retry(..., refrescar_doc_refs=False)` clears stamp only when True; `process_oc_match_job(job_id)` unchanged
- [x] 3.4 Router `Body(default_factory=OcMatchRetryRequest)`; empty POST 200
- [x] 4.1 `retry(id, { refrescar_doc_refs } = {})` posts JSON `{ refrescar_doc_refs }`
- [x] 4.2 Checkbox in `.actions` when `showRetry`; default off; reset on `selected.id`; locked label
- [x] 4.3 `.checkboxLabel` copied from ModalPedidoCompra; CF tokens only
- [x] 4.4 `maxLength={500}` on Factura/s and Pedido/s in ModalPedidoCompra + ModalCorregirPedido; Detalle untouched
- [x] 5.1 Default `queue_retry` keeps stamp; `True` clears it
- [x] 5.2 Bool True on factura/proforma; False on `comprobante_pago`/`otro`/empty
- [x] 5.3 Stamped skip; refresh append (no wipe); skip-tipo no stamp; Excel error still stamps when unset
- [x] 5.4 Empty POST keeps stamp; body true clears; view-only 403 with or without flag
- [x] 5.5 Schema ValidationError (>500); TabOcMatch checkbox gate + payload; focused commands run
- [x] 6.1 This file

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && ./venv/bin/pytest tests/unit/test_oc_match_reclaim.py tests/unit/test_oc_match_doc_refs.py tests/integration/test_oc_match_enqueue.py tests/integration/test_oc_match_worker.py tests/unit/test_schemas_compras.py -q --tb=short` → **69 passed** in 12.25s. `cd frontend && pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx` → **13 passed** in 3.98s |
| Runtime harness command/scenario and exact result | N/A — no routing, shell, subprocess, or process-integration boundary; pytest + jsdom cover stamp/skip/refresh/max_length/checkbox |
| Rollback boundary | Downgrade `compras_043` (drop `doc_refs_aplicado_at`) + revert design file list: model, schemas, `doc_refs`/`enqueue`/`worker`, router retry body, `useOcMatch`, TabOcMatch + CSS, two pedido modals, focused tests. Text columns and `numero_factura` stay. |

## Deviations from Design

None — implementation matches design. Worker flushes after stamping so the same persist session (and tests that `refresh` the job) see `doc_refs_aplicado_at`.

## Issues Found

None.

## Workload / PR Boundary

- Mode: single PR (stacked on PR #1314 until it merges)
- Current work unit: doc-refs-retry-guard
- Boundary: `compras_043` + write-once stamp + retry body/checkbox + max_length 500
- Estimated review budget impact: Low; tracked authored slice 383+/48- (OpenSpec artifacts excluded from settle budget)

## Status

19/19 tasks complete. Ready for verify.
