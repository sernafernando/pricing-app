# Tasks: PedidoCompra OC-match doc refs

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350–550 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Columns + extract/write-back + pedido APIs + three modals | PR 1 | `pytest tests/unit/test_oc_match_doc_refs.py tests/unit/test_pedidos_{service,corregir}.py tests/integration/test_oc_match_worker.py` | N/A — no modal tests; MIME enqueue unchanged | Downgrade + revert pipeline/`doc_refs` + pedido APIs + three modals |

## Phase 1: Branch

- [x] 1.1 Create `feat/compras-oc-match-pedido-doc-refs` from `upstream/main` (not develop). Do not commit to main.

## Phase 2: Model + Alembic

- [x] 2.1 Create `backend/alembic/versions/compras_042_pedido_doc_refs.py`: two Text NULL; `down_revision = compras_041_oc_match_progress_phase`; no index; rehang if tip moved. Downgrade drops both.
- [x] 2.2 Add `facturas_documento` + `pedidos_documento` after `observaciones` on `backend/app/models/pedido_compra.py`. Leave `numero`/`numero_factura`.

## Phase 3: Extract tipo_documento

- [x] 3.1 In `backend/app/services/oc_match/extract.py` add `tipo_documento` enum to JSON + prompt. Keep `nro_documento` / `nro_pedido`.
- [x] 3.2 In `backend/app/services/oc_match/match.py` pass `tipo_documento` through.
- [x] 3.3 In `backend/app/services/oc_match/acta.py` add one `Tipo documento:` line after nro documento (spec: Factura extract includes tipo).
- [x] 3.4 In `backend/tests/unit/test_oc_match_pipeline.py` assert that acta line; add `doc_refs.py` to the mail-ban list.

## Phase 4: Write-back + worker

- [x] 4.1 Create `backend/app/services/oc_match/doc_refs.py`: normalize aliases (`nv`→`nota_venta`; `recibo`→`comprobante_pago`; unknown→`otro`), parse `;`, append_unique, route, `apply_writeback`.
- [x] 4.2 Create `backend/tests/unit/test_oc_match_doc_refs.py`: factura both columns; proforma→Pedido/s; skip `comprobante_pago|otro`; `A; B` + `a` no-op then `C`; never `numero_factura`.
- [x] 4.3 In `backend/app/services/oc_match/worker.py` keep `extracted`; after fence + renglones, `SELECT FOR UPDATE` + `apply_writeback`. Never `editar_pedido`. Write if extract ran and tipo is routeable, including `RechazoExcel`. Leave `backend/app/services/oc_match/enqueue.py` (read-only).
- [x] 4.4 In `backend/tests/integration/test_oc_match_worker.py`: GOLDEN `factura` writes; duplicate no-op; RechazoExcel writes; missing extract does not.

## Phase 5: Pedido APIs

- [x] 5.1 On `backend/app/schemas/pedido_compra.py` add both fields (`str | None = None`) to Base, Update, CorreccionPedidoRequest. No `max_length`.
- [x] 5.2 In `backend/app/services/pedidos_service.py` add both to `CAMPOS_EDITABLES_BORRADOR` + `CAMPOS_EDITABLES_APROBADO`; wire `crear_pedido` kwargs; clone inherit; exclude `CAMPOS_FINANCIEROS_CORRECCION`.
- [x] 5.3 In `backend/app/routers/administracion_compras.py` pass both kwargs into `crear_pedido`.
- [x] 5.4 In `backend/tests/unit/test_pedidos_service.py`: both editable when aprobado; PUT skips `match_forward` (spec: PUT replaces the stored string).
- [x] 5.5 In `backend/tests/unit/test_pedidos_corregir.py`: clone inherits both; financial rules unchanged (spec: Corregir inherits both columns).

## Phase 6: Minimal FE

- [x] 6.1 In `frontend/src/components/compras/ModalPedidoCompra.jsx` add Factura/s + Pedido/s state, create + metadata PUT, two inputs after `numero_factura`. `|| null` cannot wipe.
- [x] 6.2 In `frontend/src/components/compras/ModalPedidoDetalle.jsx` add two info rows after N° Factura; null → `—` (spec: Empty detail shows dash).
- [x] 6.3 In `frontend/src/components/compras/ModalCorregirPedido.jsx` add state, fields, payload only when changed. No list/chip redesign.

## Phase 7: Apply-progress

- [x] 7.1 Write `openspec/changes/feat-compras-oc-match-pedido-doc-refs/apply-progress.md`: completed tasks, focused test, N/A harness, rollback. Skip `frontend/src/novedades/2026-09-21-oc-match.md` (read-only).
