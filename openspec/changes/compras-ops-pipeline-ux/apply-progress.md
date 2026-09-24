# Apply Progress: compras-ops-pipeline-ux

**Change**: compras-ops-pipeline-ux
**Mode**: Standard
**Branch**: `feature/compras-ux` (tracker)
**Delivery**: feature-branch-chain (user confirmed)
**HEAD after Phase 0**: `d78e8b38` (fast-forward from `d4b19e4d` onto `upstream/main`)

## Completed Tasks

- [x] 0.1 Rebase/merge upstream main (read-only) so facturas_documento/pedidos_documento exist (PRs 1314/1316/1317) before seed Alembic. Test: columns present.
- [x] 1.1 RED `backend/tests/unit/test_pedido_factura_documentos.py`: empty 422; `A-1; A-2; ;A-3` → 3; ERP ≠ cargada.
- [x] 1.2 GREEN `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` + `backend/app/models/pedido_factura_documento.py` + `backend/app/models/pedido_compra.py`. Test: seed; raw kept.
- [x] 1.3 `backend/app/services/pedidos_service.py` + `backend/app/schemas/pedido_compra.py`. Test: default mercadería; PM PATCH tipo 403; backfill `creado_por_id`.
- [x] 1.4 POST/DELETE factura in `backend/app/routers/administracion_compras.py`. Test: 201; 2m 204 / 6m 409.
- [x] 1.5 `eje_procesal` + chips in `frontend/src/components/compras/TabPedidosCompra.jsx` + `frontend/src/components/compras/ModalPedidoDetalle.jsx`. Test: `n_a_servicio` / `por_recibir`.
- [x] 1.6 `backend/app/schemas/orden_pago.py` `pedidos_numeros` + `frontend/src/components/compras/TabOrdenesPago.jsx`. Test: two `P-…`; `a_cuenta` empty. Docs `docs/modulos/compras-guia-usuario.md`.

## Work Unit Evidence

### Phase 0 (prior batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `git merge-base --is-ancestor upstream/main HEAD` → exit 0. `git rev-list --left-right --count upstream/main...HEAD` → `0 0`. Columns `facturas_documento` / `pedidos_documento` present. |
| Runtime harness command/scenario and exact result | N/A — Phase 0 is git-only (no runtime/process boundary). |
| Rollback boundary | `git reset --hard d4b19e4d` on `feature/compras-ux` (pre-ff). |

### Phase 1 PR1 backend (1.1–1.4)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db SECRET_KEY=ci-test-secret-key-minimum-32-bytes! ERP_BASE_URL=http://localhost:9 RATE_LIMIT_STORAGE_URI=memory:// /home/user/.herdr/worktrees/pricing-app/feature-admin-ocs/backend/venv/bin/python -m pytest tests/unit/test_pedido_factura_documentos.py -q --tb=short` → **14 passed**. Smoke: `test_pedidos_service.py` + `test_pedidos_vincular_factura.py` + `test_pedidos_corregir.py` + schema create → **95 passed**. |
| Runtime harness command/scenario and exact result | N/A — no live DB/alembic upgrade in this worktree (SQLite `create_all` + Python seed function). Production path is `alembic upgrade head` to `compras_044_pipeline_tipo_responsable_facturas`. |
| Rollback boundary | Drop/revert `compras_044` (table `pedido_factura_documentos` + cols `tipo`, `responsable_id`, `faltantes_resuelto_en`); revert service/router/schema/test files. Does not touch 1.5–1.6 FE or PR2 alerts. |

### Phase 1 PR1 visibility (1.5–1.6)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db SECRET_KEY=ci-test-secret-key-minimum-32-bytes! ERP_BASE_URL=http://localhost:9 RATE_LIMIT_STORAGE_URI=memory:// /home/user/.herdr/worktrees/pricing-app/feature-admin-ocs/backend/venv/bin/python -m pytest tests/unit/test_eje_procesal.py -q --tb=short` → **13 passed**. Combined with factura suite: `test_eje_procesal.py` + `test_pedido_factura_documentos.py` → **27 passed**. |
| Runtime harness command/scenario and exact result | N/A — derived DTO + list-column wiring; no new process/DB boundary. Chips/OP numbers are computed in-process from existing tables (`pedido_factura_documentos`, `compras_oc_match_jobs`, `imputaciones`). Browser E2E not run in this slice (no live frontend server in the apply budget). |
| Rollback boundary | Revert schema fields `eje_procesal`/`oc_vinculada`/`oc_match_status`/`pedidos_numeros`, mapper/batch helpers in `pedidos_service.py`, router overlays, FE columns/chips, `test_eje_procesal.py`, and the two paragraphs in `docs/modulos/compras-guia-usuario.md`. Does not revert `compras_044` or 1.1–1.4. |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| (tracked tree) | Fast-forward | Phase 0: `d4b19e4d..d78e8b38` onto `upstream/main`. |
| `backend/tests/unit/test_pedido_factura_documentos.py` | Created | RED/GREEN unit+HTTP tests: seed, 422, ERP≠cargada, tipo/responsable gates, 201/204/409. |
| `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` | Created | `tipo`+ck, `responsable_id` backfill, `faltantes_resuelto_en`, factura table, `;` seed. |
| `backend/app/models/pedido_factura_documento.py` | Created | Normalized factura row model. |
| `backend/app/models/pedido_compra.py` | Modified | `tipo`, `responsable_id`, `faltantes_resuelto_en`, rels, before_insert backfill. |
| `backend/app/models/__init__.py` | Modified | Register `PedidoFacturaDocumento`. |
| `backend/app/schemas/pedido_compra.py` | Modified | `tipo`, `responsable_id`, factura rows, then `eje_procesal`, `oc_vinculada`, `oc_match_status`. |
| `backend/app/services/pedidos_service.py` | Modified | Defaults, D-PERMS gates, seed/CRUD factura, 5m undo; mapper `calcular_eje_procesal`; chip + OP-number batches. |
| `backend/app/routers/administracion_compras.py` | Modified | PATCH alias; POST/DELETE factura-documentos; list/detail overlays for procesal/chips/`pedidos_numeros`. |
| `backend/tests/conftest.py` | Modified | Import factura model for `create_all`. |
| `backend/app/schemas/orden_pago.py` | Modified | `pedidos_numeros: list[str]` on list/detail response. |
| `backend/tests/unit/test_eje_procesal.py` | Created | Mapper parametrize + chips latest-job + two `P-…` / `a_cuenta` empty. |
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | Proceso column: `eje_procesal` + OC/factura/Match chips. Estado badge unchanged. |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified | Proceso/chip tokens (CF). |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modified | Proceso + chips next to financial estado. |
| `frontend/src/components/compras/ModalPedidoDetalle.module.css` | Modified | Chip row styles. |
| `frontend/src/components/compras/TabOrdenesPago.jsx` | Modified | Pedidos column lists all `pedidos_numeros`. |
| `docs/modulos/compras-guia-usuario.md` | Modified | Short operator notes for Proceso chips and OP Pedidos column. |
| `openspec/changes/compras-ops-pipeline-ux/tasks.md` | Modified | 0.1 and 1.1–1.6 `[x]`. |
| `openspec/changes/compras-ops-pipeline-ux/design.md` | Modified | One-line correction: PR1 Alembic is `compras_044` (042/043 already on main). |
| `openspec/changes/compras-ops-pipeline-ux/apply-progress.md` | Modified | This checkpoint (merged 1.1–1.6). |

## Deviations from Design

- Alembic revision is **`compras_044`** not `compras_042` because main already has `compras_042_pedido_doc_refs` and `compras_043_oc_match_doc_refs_aplicado`. Noted in design.md (prior batch).
- Alert fan-out / undo retract intentionally omitted (PR2). Empty numero still 422 and creates no `Notificacion`.
- `oc_vinculada` uses header `oc_poh_id` only (PR4 relation table not yet applied).
- `oc_match_status` is latest `compras_oc_match_jobs.status` by max job id; null when no job.
- Financial `EstadoBadge` mapping for `aprobado` → "Pendiente" was **not** changed (spec: do not rename).
- No Vitest: no existing TabPedidos/TabOrdenes test nearby; coverage is pytest mapper + batch.

## Issues Found

- HTTP DELETE 409 path calls `db.rollback()`; tests that only `flush()` the new row lose it. Tests now `commit()` before the undo request. (prior batch)
- None new in 1.5–1.6.

## Remaining Tasks

- [ ] 2.1–2.5 PR2 alerts
- [ ] 3.1–3.4 PR3 Depósito
- [ ] 4.1–4.5 PR4 multi-OC
- [ ] 5.1 Verify docs / ERP untouched

## Workload / PR Boundary

- Mode: chained PR slice (feature-branch-chain)
- Current work unit: PR1 visibility 1.5–1.6
- Boundary: derived `eje_procesal` + chips on pedido list/detail; OP `pedidos_numeros` + FE column + light docs. Stops before PR2 alerts.
- Estimated review budget impact: this slice is backend mapper/schema + two FE tables; PR1 as a whole (1.1–1.6) still likely exceeds the 400-line review budget and should stay one chained PR1 or be split at 1.4/1.5 if review requires it.

## Attempt Settlement

- Token: `sha256:26f4ee7af648599dbe1f28bb54880a1f749c35f1bb07baf772dec807edc54197`
- Request: `settle-pr1-fe-156-01`
- Inventory (acquire): `sha256:24a7b585b9525def4294cd88d8d1c1ff52a3e4b2080abccf9c33232718c4dc8c` drifted after `test_eje_procesal.py`; settle exclude `sha256:3eae4166edcfd51abbcfb29dade7061eb56c71c658ecaf730b500bc3e0e9a29b`.

## Status

7/22 tasks complete. PR1 (1.1–1.6) ready as a chained slice. Not ready for verify until Phases 2–5 land.
