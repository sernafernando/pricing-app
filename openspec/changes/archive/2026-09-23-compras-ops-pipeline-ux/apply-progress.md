# Apply Progress: compras-ops-pipeline-ux

## Completed

### Phase 0
- [x] 0.1 Rebase/merge upstream main — `facturas_documento` / `pedidos_documento` present.

### Phase 1 (PR1 → #1320)
- [x] 1.1–1.4 Backend: `compras_044`, factura documento rows, tipo/responsable, POST/DELETE undo window.
- [x] 1.5–1.6 FE: `eje_procesal` + chips; OP `pedidos_numeros`; docs touch.

### Phase 2 (PR2 alerts → #1322)
- [x] 2.1 RED `backend/tests/unit/test_compras_alertas_service.py`
- [x] 2.2 GREEN `backend/app/services/compras_alertas_service.py` (+ wire factura create/undo in `pedidos_service`)
- [x] 2.3 PATCH `/api/notificaciones/{id}/ok` + `/snooze`; hide until mark+1h
- [x] 2.4 Faltantes → `responsable_id` + `faltantes_texto`; resolve fan-out `deposito.recibir_mercaderia`
- [x] 2.5 `AppLayout` stacks `compras.factura_cargada` / `compras.faltantes` / `compras.faltantes_resuelto`; OK → DESCARTADA

### Phase 3 (PR3 Depósito → #1323)
- [x] 3.1 AND `q_proveedor|q_numero|q_factura|q_empresa` on `listar_pedidos`
- [x] 3.2 Undo `recibido` (pagado / CC via D-UNDO-R); optional obs; `faltantes_texto` required; `recepcion_undo_recibido`
- [x] 3.3 FE tab: Por recibir = pagado default + CC toggle; hide saldo 0; Docs=adjuntos; `?focus=observaciones`
- [x] 3.4 Servicio (`tipo=servicio`) → 409 on recepción actions (`n_a_servicio`)

### Phase 4 (PR4 multi-OC → #1324)
- [x] 4.1 RED `backend/tests/integration/test_vincular_oc_multi.py`: add-not-replace; dup/servicio 409; partial 422; 1/2 open; last → controlado
- [x] 4.2 GREEN Alembic **`compras_045_pedido_compra_ocs`** (`down_revision` = `compras_044_pipeline_tipo_responsable_facturas`) + model `pedido_compra_oc.py`. First-link copied on migrate. **Not `compras_043`** (already used on main/PR1).
- [x] 4.3 `pedidos_service.vincular_oc` INSERT relation + header first-link cache; servicio 409; duplicate 409; partial 422. `oc_ingresos_service` servicio → empty candidatas.
- [x] 4.4 `recepcion_service` controlado iff all linked OCs; 1/2 complete stays `recibido`; last → controlado.
- [x] 4.5 FE: N OC blocks on Depósito; ModalVincularOC servicio empty. RTL 2 headings + servicio empty.

### Phase 5 (docs on `feat/compras-ops-pipeline-04-multi-oc`)
- [x] 5.1 `docs/modulos/compras-guia-usuario.md`: in-app only (banner + campanita; no email/Slack); ERP multi-factura deprecated/untouched; financial badge `aprobado` kept; tipo mercadería/servicio; factura = rows; Depósito pagado+CC / undo / Docs=adjuntos; multi-OC N blocks / servicio no OC.

## TDD Cycle Evidence

| Task | RED | GREEN | REFACTOR |
|---|---|---|---|
| 4.1 | `test_vincular_oc_multi.py` written first (add-not-replace / 409 / 422) | 4.2–4.4 implementation | none material |
| 4.2 | implied by 4.1 import of `PedidoCompraOc` | `compras_045` + model | design/tasks id corrected 043→045 |
| 4.3 | 4.1 HTTP cases | INSERT relation+header | old S1 “Unlink first” test updated |
| 4.4 | 4.1 `TestControladoIffAllOcs` | `recalcular_estado` + `computar_saldos` all OCs | existing recepción 99 still green |
| 4.5 | RTL 2 blocks + Modal servicio empty | FE grouping + empty copy | CSS tokens only |
| 5.1 | N/A docs-only (Standard mode) | guide + tasks checkbox | concise bullets, not rewrite |

## Work Unit Evidence

### PR4 (prior slice)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_vincular_oc_multi.py tests/integration/test_oc_vincular_s1_endpoints.py tests/integration/test_recepcion_deposito_endpoints.py -q` → **129 passed** (27.36s). `pnpm exec vitest run --project=unit src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/ModalVincularOC.test.jsx` → **44 passed** (2 files). `ruff format --check` on touched Python: pass. `pnpm test css-guard`: **8 passed**. eslint on touched FE: pass. |
| Runtime harness command/scenario and exact result | N/A — no live server in this worktree; add-not-replace / 409 / 422 / all-OC controlado covered by pytest HTTP/service fixtures; N blocks + servicio empty covered by RTL. |
| Rollback boundary | Revert this branch (`feat/compras-ops-pipeline-04-multi-oc`) onto PR3 tip `8d61f23c`. Files: `compras_045_pedido_compra_ocs.py`, `pedido_compra_oc.py`, `pedidos_service.py`, `recepcion_service.py`, `oc_ingresos_service.py`, schemas, `TabRecepcionDeposito.*`, `ModalVincularOC.*`, `test_vincular_oc_multi.py`. Downgrade `compras_045`. |

### Phase 5.1 (this slice)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `true` → exit 0 (docs-only; no pytest/vitest). |
| Runtime harness command/scenario and exact result | N/A — operator guide copy; no runtime boundary. |
| Rollback boundary | Revert `docs/modulos/compras-guia-usuario.md`, `openspec/changes/compras-ops-pipeline-ux/tasks.md`, `openspec/changes/compras-ops-pipeline-ux/apply-progress.md`. Product code untouched. |

## Verification (this slice)

- Channel lock: in-app only (banner + campanita); no email/Slack documented.
- ERP multi-factura lock: guide states deprecated/untouched; FAQ confirms no change.
- Badge lock: **aprobado** kept (explicitly not renamed to Pendiente).
- Spot-check PR1–PR4 (`b70a7f82^..HEAD`): `ModalVincularFactura*` not in range; `POST /vincular-factura` / `desvincular-factura` only comment-adjacent to OC comments; `es_factura_cargada` docstring: ERP `ct_transaction` is never identity.
- `#1324` CI green (orchestrator). Docs-only; no product reopen.

## Deviations from Design

- Alembic filename is `compras_045_pedido_compra_ocs.py` instead of design’s original `compras_043` — main/PR1 already consumed 042/043/044. Design + tasks updated.
- `desvincular-oc` still clears **all** relation rows + header (existing single-unlink API). Not in 4.1–4.5 as a new endpoint.
- 5.1: none — guide matches locked decisions (`channel: in_app_only`, `invoice_erp_multi_link: deprecated_untouched`, no `aprobado` rename).

## Remaining Tasks

None. 22/22 complete. Ready for verify.

## Workload / PR Boundary

- Mode: chained PR slice (feature-branch-chain)
- Current work unit: Phase 5.1 docs (lands on PR4 branch `feat/compras-ops-pipeline-04-multi-oc`)
- Boundary: operator guide + tasks checkbox + apply-progress. No product code. No archive.
- Estimated review budget impact: small markdown only.

## Attempt Settlement

- Token: `sha256:cfb4602d048fe93e2a006018030229338a3cce726f4999c5b441d695ac667e85`
- Request: `settle-p5-docs-51-20260923`
- Inventory (exclude): `sha256:e69e3fa6db66e358ea76b436641f90e7e20c7acd278d9d5e4a8368659106bacd`
- `.gentle-ai-instance` left untracked.
- Prior PR4 settle `settle-pr4-multi-oc-04` was blocked `maintainer_decision` (line budget); this token is the Phase 5.1 acquire.

## Status

22/22 tasks complete. Ready for verify.
