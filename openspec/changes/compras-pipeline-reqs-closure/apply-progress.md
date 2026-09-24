# Apply Progress: compras-pipeline-reqs-closure

Chain strategy: feature-branch-chain (Gabe 2026-09-23)
Base branch tip at start: feat/compras-ops-pipeline-04-multi-oc @ 563fedf0
Branch: feat/compras-pipeline-reqs-closure-01-be
Mode: Standard (not Strict TDD)

## Phase 1 — BE 15+17
- [x] complete (tasks 1.1–1.7)

### Work Unit Evidence (WU1 / PR1 tracker)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_recepcion_resolver_faltantes.py tests/unit/test_eje_procesal.py tests/unit/test_compras_alertas_service.py tests/unit/test_notificacion_service.py tests/integration/test_recepcion_deposito_endpoints.py::TestResolverFaltantesHttp tests/integration/test_recepcion_deposito_endpoints.py::TestListarPedidosEjeTipo -q` → **51 passed** |
| Runtime harness command/scenario and exact result | N/A — design threat matrix is N/A; no new routing/shell/process boundary. HTTP coverage is TestClient in the focused suite (422/403/409 + eje list). |
| Rollback boundary | Phase 1 only: revert this slice’s BE + tests + SDD artifacts on `feat/compras-pipeline-reqs-closure-01-be`. Restores optional texto, old G31, dismissible OK, depósito writer. No Alembic. |

### Completed
- 1.1 `ResolverFaltantesRequest.texto` required (strip nonempty → 422)
- 1.2 resolver requires texto; 409 if not `con_faltantes` or already stamped; keeps `estado=con_faltantes`; writer = responsable OR `administracion.gestionar_ordenes_compra`
- 1.3 router uses `get_current_user`; depósito-only (not responsable) → 403
- 1.4 `retractar_faltantes(pedido_id)`; G31 copy includes texto + `?tab=deposito&pedido={id}`; `codigo_producto` via `crear_notificaciones_para_permisos`
- 1.5 `/ok`, `/descartar`, `/bulk-descartar` → 409 for `compras.faltantes`; snooze and factura OK unchanged
- 1.6 `eje_procesal` comma-OR + `tipo` on `GET /pedidos`; Depósito list forces `tipo=mercaderia` (excludes servicio)
- 1.7 unit + integration tests as listed

### Deviations
None — implementation matches design. Depósito listing forces `tipo=mercaderia` rather than documenting a caller default.

## Phase 2 — FE 15+17
- [x] complete (tasks 2.1–2.6)
Branch: feat/compras-pipeline-reqs-closure-02-fe (tip was Phase1 cea09e65)
Work unit: phase2-fe-15-17 / evidence-goal phase2-resolver-ui-tabs-banner
Authored lines this slice: 336 insertions + 24 deletions (360) — under 550 acquire cap.

### Work Unit Evidence (WU2 / PR2 ← PR1)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/AppLayout.comprasBanners.test.jsx src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/TabPedidosCompra.test.jsx` → **60 passed** (4 files) |
| Runtime harness command/scenario and exact result | N/A — design threat matrix is N/A; no new routing/shell/process boundary. UI coverage is jsdom vitest (resolver POST, no-dismiss banner + snooze, eje tab params, `?pedido=` land/expand, eje label). |
| Rollback boundary | Phase 2 only: revert this slice’s FE + tests + SDD task/progress marks on `feat/compras-pipeline-reqs-closure-02-fe`. Restores dismissible faltantes OK, old Recibidos/`con_faltantes` estado queries, “Faltantes resueltos” label, no resolver form. Does not revert Phase 1 BE. |

### Completed
- 2.1 `resolverFaltantes` POST `/administracion/compras/pedidos/{id}/faltantes/resolver` `{texto}`
- 2.2 Detalle: required textarea when `faltantes_sin_res`; hide after stamp; label “Faltantes con resolución”
- 2.3 AppLayout: `compras.faltantes` not dismissible; Ver + Posponer (`/snooze`); campanita hides DELETE for that tipo
- 2.4 Recibidos `eje_procesal=recibido,faltantes_con_res`; Con faltantes `faltantes_sin_res`; `?pedido=` lands Recibidos and expands
- 2.5 Pedidos list eje label “Faltantes con resolución”
- 2.6 vitest in the four assigned files

### Deviations
None — implementation matches design.

### Residual risks (not in this slice)
- `pages/Notificaciones.jsx` still calls PATCH `/descartar` (BE 409). Not campanita; left as risk note.
- FE does not call PATCH `/estado` DESCARTADA. No cheap FE block needed.

## Phase 3 — Depósito ID
- [x] complete (tasks 3.1–3.3)
Branch: feat/compras-pipeline-reqs-closure-03-deposito-id (from Phase2 tip 2e31e2fc)
Work unit: phase3-deposito-id / evidence-goal phase3-cargada-badge-ident-chips
Authored lines this slice: 128 insertions + 31 deletions (159) before apply-progress write — under 400 acquire cap.

### Work Unit Evidence (WU3 / PR3 ← PR2)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` → **53 passed** (1 file) |
| Runtime harness command/scenario and exact result | N/A — design threat matrix is N/A; no new routing/shell/process boundary. UI coverage is jsdom vitest (badge iff `factura_cargada`, CON-OC + SIN-OC ident chips, 60ch truncate). |
| Rollback boundary | Phase 3 only: revert this slice’s FE + tests + guia + SDD marks on `feat/compras-pipeline-reqs-closure-03-deposito-id`. Restores CON-OC XOR (no factura/pedidos_documento chips), no Cargada badge, guia “OC vinculada” without the GBP clarification. Does not revert Phase 1–2. |

### Completed
- 3.1 Cargada badge iff `factura_cargada === true` (`badgeControlado`); `identChips` (factura + `pedidos_documento` + observaciones, 60ch+title) on all rows including CON-OC (itemsBadge no longer XORs chips away)
- 3.2 Guía: OC chip = vinculación in Pricing, not “exists in GBP”; ERP-missing copy stays
- 3.3 vitest: badge on/off, CON-OC + SIN-OC chips, pedidos_documento truncate

### Deviations
None — implementation matches design. Observaciones chip kept (existing SIN-OC behavior) so prior header-chip tests do not regress.

## Phase 4–5
- [ ] pending
