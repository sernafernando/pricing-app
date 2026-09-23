# Tasks: Compras Pipeline Chicho Review Fixes

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 520–780 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | #1320 → #1322 → #1323 → #1324 |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Match persist + 044 | PR1 #1320; base=`feature/compras-ux` | `pytest tests/unit/test_pedido_factura_documentos.py tests/integration/test_oc_match_worker.py -q` | N/A — pytest txn | revert persist + 044 |
| 2 | Permiso + banner cap | PR2 #1322; base=#1320 | `pytest tests/unit/test_compras_alertas_service.py -q` + `pnpm exec vitest run src/components/AppLayout.comprasBanners.test.jsx` | N/A — unit/RTL | revert 046 + alerts + cap |
| 3 | Undo tests only | PR3 #1323; base=#1322 | `pytest tests/integration/test_recepcion_deposito_endpoints.py -k undo -q` | N/A — D-UNDO-R live | revert tests |
| 4 | ERP UI + 1-of-3 + novedad | PR4 #1324; base=#1323 | `pytest tests/integration/test_vincular_oc_multi.py -q` + `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` | N/A — Gabe gate | revert Tab/docs; drop draft |

Locks: persist after `apply_writeback` same txn; `created_by_id=pedido.creado_por_id`; 046 parent=`compras_045` (applied); no GET seed; SUPERADMIN via PermisosService; no admin-ocs.

## Phase 1: PR1 #1320 — Match alta + amend 044

- [x] 1.1 Extract persist from `agregar_factura_documento` in `backend/app/services/pedidos_service.py`: skip `len>100` (log) or casefold-dupe; insert + notify.
- [x] 1.2 Harden `seed_factura_documentos` in `backend/app/services/pedidos_service.py` (100/casefold/no re-seed). Never call from chips/GET/list.
- [x] 1.3 After `apply_writeback` in `backend/app/services/oc_match/worker.py` same txn, persist with `created_by_id=pedido.creado_por_id`.
- [x] 1.4 Add `UniqueConstraint(pedido_id, numero)` on `backend/app/models/pedido_factura_documento.py`.
- [x] 1.5 Amend `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py`: skip `len>100` (log), casefold-dedupe, UNIQUE, first-seen casing.
- [x] 1.6 Tests in `backend/tests/unit/test_pedido_factura_documentos.py` + `backend/tests/integration/test_oc_match_worker.py`: overflow/casefold/UNIQUE; Match `FA-10` chip-on; no falta-factura.

## Phase 2: PR2 #1322 — Permiso + banners

- [x] 2.1 Create `backend/alembic/versions/compras_046_seed_ver_alertas_factura.py` like compras_020: catalog `administracion.ver_alertas_factura`, no roles, `orden=176`, parent `compras_045`.
- [x] 2.2 In `backend/app/services/compras_alertas_service.py` set `destinatarios_factura` via `resolver_usuarios_con_algun_permiso(["administracion.ver_alertas_factura"])`. Drop `ROLES_FACTURA`/MarcaPM. Faltantes=`responsable_id`.
- [x] 2.3 Tests in `backend/tests/unit/test_compras_alertas_service.py`: holders only; ADMIN without code out; SUPERADMIN via resolver; faltantes unchanged.
- [x] 2.4 Cap `comprasAlertas` to `max_alertas_visibles` in `frontend/src/components/AppLayout.jsx`; `+N más` in `frontend/src/components/AppLayout.module.css`. No compras timed-rotate.
- [x] 2.5 In `frontend/src/components/AppLayout.comprasBanners.test.jsx`: 7/cap 3 → 3 banners + `+4 más`; unread stays until OK.

## Phase 3: PR3 #1323 — Undo tests (D-UNDO-R)

- [ ] 3.1 Tests only in `backend/tests/integration/test_recepcion_deposito_endpoints.py`: second undo 409; CC+`pagado_en` → `pagado`; HTTP 403 via `require_permiso("deposito.recibir_mercaderia")`.

## Phase 4: PR4 #1324 — ERP UI + 1-of-3 + novedad GATE

- [ ] 4.1 Always render one OC block in `frontend/src/components/compras/TabRecepcionDeposito.jsx`; copy `OC no encontrada en ERP` if ERP empty.
- [ ] 4.2 Tests in `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`: empty-ERP block + sibling with lines.
- [ ] 4.3 In `backend/tests/integration/test_vincular_oc_multi.py`: 1-of-3 stays `recibido` or `faltantes_*`.
- [ ] 4.4 Document unlink-all in `docs/modulos/compras-guia-usuario.md`.
- [ ] 4.5 **GATE:** write `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md`. Stop. Show Gabe. Do not commit until he reviews.
