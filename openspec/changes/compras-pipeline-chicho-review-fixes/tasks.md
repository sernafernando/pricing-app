# Tasks: Compras Pipeline Chicho Review Fixes

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines (this amend) | 450–700 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | #1320 → #1322 → #1323 → #1324 → **PR5** → **PR6** |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Match persist + 044 | PR1 #1320; **landed** | `pytest tests/unit/test_pedido_factura_documentos.py tests/integration/test_oc_match_worker.py -q` | N/A | revert persist + 044 |
| 2 | Permiso + banner cap | PR2 #1322; **landed** | `pytest tests/unit/test_compras_alertas_service.py -q` + `pnpm exec vitest run src/components/AppLayout.comprasBanners.test.jsx` | N/A | revert 046 + alerts + cap |
| 3 | Undo tests only | PR3 #1323; **landed** | `pytest tests/integration/test_recepcion_deposito_endpoints.py -k undo -q` | N/A | revert tests |
| 4 | ERP UI + 1-of-3 + novedad | PR4 #1324; 4.1–4.4 landed | `pytest tests/integration/test_vincular_oc_multi.py -q` + `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` | N/A | revert Tab/docs |
| 5 | Stop notify + cargada cols + PATCH + timer | **PR5**; base=#1324 tip | `pytest tests/unit/test_pedido_factura_documentos.py tests/unit/test_compras_alertas_service.py tests/integration/test_oc_match_worker.py -q` | N/A — inject `ahora` | revert 047 + persist notify removal + PATCH |
| 6 | FE checkbox/chip + novedad rewrite | **PR6**; base=PR5 | `pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/compras/TabPedidosCompra.test.jsx` | N/A — Gabe gate | revert FE + drop rewritten draft |

Locks: persist after `apply_writeback` same txn; **no notify on persist/Match**; `cargada` default false (no backfill); two 5-min constants; sweep + injectable `ahora`; no GET seed; no admin-ocs; SUPERADMIN via PermisosService.

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

- [x] 3.1 Tests only in `backend/tests/integration/test_recepcion_deposito_endpoints.py`: second undo 409; CC+`pagado_en` → `pagado`; HTTP 403 via `require_permiso("deposito.recibir_mercaderia")`.

## Phase 4: PR4 #1324 — ERP UI + 1-of-3 + novedad GATE

- [x] 4.1 Always render one OC block in `frontend/src/components/compras/TabRecepcionDeposito.jsx`; copy `OC no encontrada en ERP` if ERP empty.
- [x] 4.2 Tests in `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`: empty-ERP block + sibling with lines.
- [x] 4.3 In `backend/tests/integration/test_vincular_oc_multi.py`: 1-of-3 stays `recibido` or `faltantes_*`.
- [x] 4.4 Document unlink-all in `docs/modulos/compras-guia-usuario.md`.
- [ ] 4.5 **SUPERSEDED by 6.3.** Original draft said Match = cargada. Do not commit that copy.

## Phase 5: PR5 — Constancia vs cargada (backend)

- [x] 5.1 Add `cargada` (bool default false), `cargada_marked_at`, `cargada_marked_by_id`, `alerta_pendiente_hasta`, `alerta_disparada_at` on `backend/app/models/pedido_factura_documento.py`. No silent backfill.
- [x] 5.2 Create `backend/alembic/versions/compras_047_factura_cargada_erp.py` parent `compras_045_pedido_compra_ocs`. Index pending `alerta_pendiente_hasta`.
- [x] 5.3 In `backend/app/services/pedidos_service.py`: remove `_notificar_factura_cargada` from `persist_factura_documento`. Add `FACTURA_CARGADA_ALERT_DELAY` **separate** from `FACTURA_UNDO_WINDOW`. `es_factura_cargada` / `chips_visibilidad_batch` = ≥1 `cargada=true`. Expose `tiene_numero_factura`. Implement `marcar_factura_cargada` (check/uncheck, idempotent re-check does not reset timer; re-check after uncheck starts a new window).
- [x] 5.4 In `backend/app/services/compras_alertas_service.py` add `disparar_alertas_factura_pendientes(session, *, ahora=None)`. Persist/alta/Match MUST NOT call notify. Uncheck before fire cancels pending. DELETE undo still retracts fired notifs.
- [x] 5.5 Create `backend/app/scripts/dispatch_factura_cargada_alerts.py` cron entry that calls the sweep. No `BackgroundTasks.sleep`.
- [x] 5.6 Add PATCH `pedidos/{id}/factura-documentos/{row_id}` in `backend/app/routers/administracion_compras.py` + Pydantic v2 body/response in `backend/app/schemas/pedido_compra.py`. Permiso `administracion.gestionar_ordenes_compra`. Include factura rows + flags on pedido detalle response.
- [x] 5.7 Rewrite tests: `test_pedido_factura_documentos.py` (row ≠ cargada; Match chip-off; DELETE undo still `created_at`; PATCH check/uncheck); `test_compras_alertas_service.py` (no notify on alta; fire at T+5; cancel on uncheck; sweep at T+4:59 no-op; holders only); `test_oc_match_worker.py` (row exists, chip off, zero notifs).

## Phase 6: PR6 — FE checkbox/chip + novedad rewrite

- [x] 6.1 In `frontend/src/components/compras/ModalPedidoDetalle.jsx`: list each factura row as constancia + ERP checkbox; PATCH on toggle; do not treat `facturas_documento` text as cargada. NV/`pedidos_documento` stay text-only.
- [x] 6.2 In `frontend/src/components/compras/TabPedidosCompra.jsx` (and detalle chips): “Factura” chip from `factura_cargada` (ERP). Optional muted “has number” only if it does not reuse the cargada label. Tests for chip-off-with-numbers and chip-on-after-check.
- [ ] 6.3 **GATE:** rewrite `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` and `docs/modulos/compras-guia-usuario.md`: constancia vs cargada; 5-min pending alert + uncheck-cancel; DELETE undo is a **different** 5-min window. Stop. Show Gabe. Do not commit until he reviews. Draft ready (novedad untracked; guía committed with 6.1–6.2). Pending Gabe OK.
