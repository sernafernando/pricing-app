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

## Phase 2–5
- [ ] pending
