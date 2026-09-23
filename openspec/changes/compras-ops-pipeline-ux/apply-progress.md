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
- [x] 2.4 Faltantes → `responsable_id` + required `faltantes_texto`; resolve fan-out `deposito.recibir_mercaderia`
- [x] 2.5 `AppLayout` stacks `compras.factura_cargada` / `compras.faltantes` / `compras.faltantes_resuelto`; OK → DESCARTADA

### Phase 3 (PR3 Depósito) — this slice
- [x] 3.1 AND `q_proveedor|q_numero|q_factura|q_empresa` on `listar_pedidos`
- [x] 3.2 Undo `recibido` (pagado / CC via D-UNDO-R); optional obs; `faltantes_texto` required; `recepcion_undo_recibido`
- [x] 3.3 FE tab: Por recibir = pagado default + CC toggle; hide saldo 0; Docs=adjuntos; `?focus=observaciones`
- [x] 3.4 Servicio (`tipo=servicio`) → 409 on recepción actions (`n_a_servicio`)

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_recepcion_deposito_endpoints.py -q` → **99 passed** (21.12s). `pnpm exec vitest run --project=unit src/components/compras/TabRecepcionDeposito.test.jsx` → **42 passed** (1 file). `ruff format --check` on touched Python: pass. `eslint` on touched FE: pass. |
| Runtime harness command/scenario and exact result | N/A — no live server in this worktree; listar AND + undo + servicio 409 covered by pytest HTTP/service fixtures; pagado+CC / hide-saldo-0 / Docs / focus covered by RTL. |
| Rollback boundary | Revert this branch (`feat/compras-ops-pipeline-03-deposito`) onto PR2. Files: `administracion_compras.py`, `recepcion.py`, `recepcion_service.py`, `test_recepcion_deposito_endpoints.py`, `TabRecepcionDeposito.jsx(+css+test)`, `useRecepcionDeposito.js`, `ModalPedidoDetalle.jsx`, `TabPedidosCompra.jsx`. No Alembic. |

## Verification (this slice)

- `ruff format --check` on touched Python: pass
- pytest `test_recepcion_deposito_endpoints.py`: **99 passed**
- Vitest `TabRecepcionDeposito.test.jsx`: **42 passed**

## Deviations from Design

- Photo remains optional via pedido adjuntos (`tipo='otro'`); no extra control-form upload field.
- `?focus=observaciones` also opens `ModalPedidoDetalle` from `TabPedidosCompra` (`?pedido=`), matching the alert deep-link `tab=pedidos`.

## Remaining Tasks

- [ ] 4.1–4.5 PR4 multi-OC
- [ ] 5.1 Verify docs / ERP untouched

## Workload / PR Boundary

- Mode: chained PR slice (feature-branch-chain)
- Current work unit: PR3 Depósito 3.1–3.4
- Branch: `feat/compras-ops-pipeline-03-deposito` (base: PR2 alerts)
- Boundary: AND filters + undo recibido + Depósito UX (pagado default, CC toggle, Docs=adjuntos, hide saldo 0, focus). Stops before multi-OC.
- Authored review lines: 834 insertions / 60 deletions (894) — above 400; this is the assigned stacked slice, report as-is.

## Attempt Settlement

- Token: `sha256:f688c73656d819b0c3acd4c33e3bba846de38aeeee2766d00469773119deea01`
- Request: `settle-pr3-deposito-01`
- Inventory (acquire): `sha256:e69e3fa6db66e358ea76b436641f90e7e20c7acd278d9d5e4a8368659106bacd`
- Settle: **blocked** `maintainer_decision` (changed-line / attempt budget). Diagnosis left for orchestrator; apply agent did not reset.

## Status

16/22 tasks complete. PR3 Depósito ready as chained slice. Not ready for verify until Phases 4–5 land.
