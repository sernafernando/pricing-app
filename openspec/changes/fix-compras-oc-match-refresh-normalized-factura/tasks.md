# Tasks: fix-compras-oc-match-refresh-normalized-factura

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–160 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | same PR #1343 |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Persist + warning on #1343 | PR #1343 | See DoD | N/A — pytest + jsdom | Revert design file list. Worker, expand, jobs route stay. |

## Phase 1: Persist (worker mirror)

- [x] 1.1 In `backend/app/services/oc_match/refresh_doc_refs.py` `_persist_writeback`: after `apply_writeback` True, if `normalize_tipo(...)=="factura"` and `token_or_none(nro_documento)`, call `pedidos_service.persist_factura_documento(db, pedido=..., numero=..., created_by_id=int(pedido.creado_por_id))` then `db.flush()`. Same session. Do not edit `worker.py`.

## Phase 2: Warning (expand unchanged)

- [x] 2.1 In `frontend/src/components/compras/TabOcMatch.jsx` add locked `title` + helper next to **Actualizar Factura/s y Pedido/s** (only when that button shows). Do not change expand, Retry, or checkbox.
- [x] 2.2 In `frontend/src/components/compras/TabOcMatch.module.css` add `.refreshHint` with CF tokens (`--cf-text-tertiary`, `--font-xs`).

## Phase 3: Tests

- [x] 3.1 In `backend/tests/unit/test_oc_match_refresh_doc_refs.py` add factura→`pedido_factura_documentos` test that does **not** mock `apply_writeback` (spy persist or assert row). Include no-op append / deleted-row restore. Pedido must have `creado_por_id`.
- [x] 3.2 In the same file, assert non-factura, empty `nro_documento`, and `apply_writeback` False skip persist. Do not mock `apply_writeback` on those cases.
- [x] 3.3 Keep `test_failed_extract_keeps_stamp`, `test_skip_if_status_left`, `test_error_job_stays_error` (do not weaken). Re-run the unit file.
- [x] 3.4 In `frontend/src/components/compras/TabOcMatch.test.jsx` assert dedicated button `title` + helper when shown; hidden for view-only. Keep expand / Retry tests.

## Definition of Done / Verification

Backend: `pytest tests/unit/test_oc_match_refresh_doc_refs.py -q --tb=short`

Frontend: `pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx`
