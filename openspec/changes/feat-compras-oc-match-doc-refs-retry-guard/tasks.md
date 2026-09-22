# Tasks: feat-compras-oc-match-doc-refs-retry-guard

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 200–350 |
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
| 1 | Stamp + max_length + retry checkbox | PR 1 | `pytest tests/unit/test_oc_match_{reclaim,doc_refs}.py tests/integration/test_oc_match_{enqueue,worker}.py -q` + `pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx` | N/A — pytest + jsdom | Downgrade `compras_043`; revert design file list |

## Phase 1: Branch

- [x] 1.1 Create `feat/compras-oc-match-doc-refs-retry-guard` from `origin/feat/compras-oc-match-pedido-doc-refs` (not ean-extract, not develop).

## Phase 2: Schema

- [x] 2.1 Add `OcMatchJob.doc_refs_aplicado_at` `DateTime(timezone=True)` NULL in `backend/app/models/oc_match_job.py`. No index.
- [x] 2.2 Create `backend/alembic/versions/compras_043_oc_match_doc_refs_aplicado.py` off `compras_042_pedido_doc_refs`. Rehang if the compras tip moved.
- [x] 2.3 Set `Field(None, max_length=500)` on both fields in Base/Update/Correccion in `backend/app/schemas/pedido_compra.py`. Text and `numero_factura` max_length=50 stay.
- [x] 2.4 Add `OcMatchRetryRequest` (`refrescar_doc_refs: bool = False`, Pydantic v2) in `backend/app/schemas/oc_match.py`. Do not add stamp to `OcMatchJobResponse`.

## Phase 3: Persist and retry

- [x] 3.1 Change `apply_writeback` in `backend/app/services/oc_match/doc_refs.py` to `-> bool`. True iff routeable tipo and ≥1 token; keep `append_unique`; never touch `numero_factura`.
- [x] 3.2 In `backend/app/services/oc_match/worker.py` `_persist`: after renglones, skip write-back when stamp set; stamp `datetime.now(UTC)` only after True; no stamp on `extracted is None`, False, or lost fence.
- [x] 3.3 In `backend/app/services/oc_match/enqueue.py` add `queue_retry(..., refrescar_doc_refs: bool = False)` and clear stamp only when True. Keep `process_oc_match_job(job_id: int)`.
- [x] 3.4 In `backend/app/routers/administracion_compras.py` accept `Body(default_factory=OcMatchRetryRequest)` on `reintentar_oc_match_job` and pass the flag. Empty POST must 200. If tests 422, switch to `Query(False)`.

## Phase 4: Frontend

- [x] 4.1 In `frontend/src/hooks/useOcMatch.js` send `retry(id, { refrescar_doc_refs } = {})` as JSON `{ refrescar_doc_refs }`.
- [x] 4.2 In `frontend/src/components/compras/TabOcMatch.jsx` add checkbox in `.actions` when `showRetry`; default off; reset on `selected.id`; locked label; pass flag.
- [x] 4.3 Copy `.checkboxLabel` from `frontend/src/components/compras/ModalPedidoCompra.module.css` (read-only) into `frontend/src/components/compras/TabOcMatch.module.css`. CF tokens only; no forms-tesla checkbox.
- [x] 4.4 Add `maxLength={500}` on Factura/s and Pedido/s in `frontend/src/components/compras/ModalPedidoCompra.jsx` and `frontend/src/components/compras/ModalCorregirPedido.jsx`. No silent slice. Do not edit `frontend/src/components/compras/ModalPedidoDetalle.jsx` (read-only).

## Phase 5: Tests

- [x] 5.1 In `backend/tests/unit/test_oc_match_reclaim.py` assert default `queue_retry` keeps stamp and `refrescar_doc_refs=True` clears it.
- [x] 5.2 In `backend/tests/unit/test_oc_match_doc_refs.py` assert bool True on factura/proforma and False on `comprobante_pago`/`otro`/empty.
- [x] 5.3 In `backend/tests/integration/test_oc_match_worker.py` cover stamped skip, refresh append (no wipe), no stamp on skip tipo, excel-error still stamps when unset (pipeline scenarios).
- [x] 5.4 In `backend/tests/integration/test_oc_match_enqueue.py` keep empty POST retry; add body `true` clears stamp; view-only still 403 (jobs scenarios).
- [x] 5.5 Assert schema 422 for field >500. Extend `frontend/src/components/compras/TabOcMatch.test.jsx`: checkbox only with Reintentar, default off, locked label, `retry` true/false. Run focused commands.

## Phase 6: Apply-progress

- [x] 6.1 Write `openspec/changes/feat-compras-oc-match-doc-refs-retry-guard/apply-progress.md` (tasks, focused tests, N/A harness, rollback = downgrade `compras_043` + design file list).
