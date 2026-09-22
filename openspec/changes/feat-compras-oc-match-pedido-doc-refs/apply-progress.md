# Apply Progress: feat-compras-oc-match-pedido-doc-refs

**Change**: feat-compras-oc-match-pedido-doc-refs
**Mode**: Standard
**Branch**: `feat/compras-oc-match-pedido-doc-refs` from `upstream/main` (`5d6ec0d6`)
**Alembic parent**: `compras_041_oc_match_progress_phase` (still the compras tip; `compras_042` hangs off it)

## Completed Tasks

- [x] 1.1 Branch from `upstream/main` (openspec change folder preserved)
- [x] 2.1 Alembic `compras_042_pedido_doc_refs` — two Text NULL, no index, downgrade drops both
- [x] 2.2 Model columns after `observaciones`; `numero` / `numero_factura` untouched
- [x] 3.1 Extract JSON + prompt include `tipo_documento` enum
- [x] 3.2 Match pass-through
- [x] 3.3 Acta one `Tipo documento:` line after nro documento
- [x] 3.4 Pipeline test asserts acta line; `doc_refs.py` on mail-ban list
- [x] 4.1 `doc_refs.py` normalize / parse / append_unique / route / `apply_writeback`
- [x] 4.2 Unit tests: factura both columns, proforma→Pedido/s, skip tipos, casefold append, never `numero_factura`
- [x] 4.3 Worker keeps `extracted`; after fence + renglones, `SELECT FOR UPDATE` + write-back; no `editar_pedido`; enqueue untouched
- [x] 4.4 Worker integration: GOLDEN factura writes; duplicate no-op; RechazoExcel writes; missing extract does not
- [x] 5.1 Schemas Base / Update / CorreccionPedidoRequest (`str | None = None`, no max_length)
- [x] 5.2 Both `CAMPOS_EDITABLES_*`; `crear_pedido` kwargs; clone inherit; not financial
- [x] 5.3 Router passes both kwargs into `crear_pedido`
- [x] 5.4 PUT replaces string; skips `match_forward`
- [x] 5.5 Clone inherits both; financial correccion unchanged
- [x] 6.1 ModalPedidoCompra Factura/s + Pedido/s (`|| null` cannot wipe)
- [x] 6.2 ModalPedidoDetalle rows after N° Factura; null → `—`
- [x] 6.3 ModalCorregirPedido payload only when changed
- [x] 7.1 This file. Novedades skipped (read-only).

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && ENVIRONMENT=testing ./venv/bin/pytest tests/unit/test_oc_match_doc_refs.py tests/unit/test_oc_match_pipeline.py tests/unit/test_pedidos_service.py tests/unit/test_pedidos_corregir.py tests/integration/test_oc_match_worker.py -q --tb=short` → **107 passed** in 23.33s |
| Runtime harness command/scenario and exact result | N/A — no modal tests; MIME enqueue unchanged; no new process/runtime boundary |
| Rollback boundary | Downgrade `compras_042` (drop two columns) + revert `doc_refs` / extract / match / acta / worker / pedido schemas+service+router / three pedido modals. `numero_factura` and enqueue stay untouched. |

## Deviations from Design

None — implementation matches design.

## Issues Found

None.

## Workload / PR Boundary

- Mode: single PR (Gabe-locked; Decision needed before apply: No)
- Current work unit: pedido-doc-refs
- Boundary: branch from `upstream/main` through columns + extract/write-back + pedido APIs + three modals
- Estimated review budget impact: Medium (350–550 forecast); authored production+test slice kept to existing `numero_factura` form patterns

## Status

20/20 tasks complete. Ready for verify.
