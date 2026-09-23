# Apply Progress: compras-ops-pipeline-ux

## Completed

### Phase 0
- [x] 0.1 Rebase/merge upstream main — `facturas_documento` / `pedidos_documento` present.

### Phase 1 (PR1 → #1320)
- [x] 1.1–1.4 Backend: `compras_044`, factura documento rows, tipo/responsable, POST/DELETE undo window.
- [x] 1.5–1.6 FE: `eje_procesal` + chips; OP `pedidos_numeros`; docs touch.

### Phase 2 (PR2 alerts) — this slice
- [x] 2.1 RED `backend/tests/unit/test_compras_alertas_service.py`
- [x] 2.2 GREEN `backend/app/services/compras_alertas_service.py` (+ wire factura create/undo in `pedidos_service`)
- [x] 2.3 PATCH `/api/notificaciones/{id}/ok` + `/snooze`; hide until mark+1h
- [x] 2.4 Faltantes → `responsable_id` + required `faltantes_texto`; resolve fan-out `deposito.recibir_mercaderia`
- [x] 2.5 `AppLayout` stacks `compras.factura_cargada` / `compras.faltantes` / `compras.faltantes_resuelto`; OK → DESCARTADA

## Verification (this slice)

- `ruff format --check` on touched Python: pass
- `pytest tests/unit/test_compras_alertas_service.py tests/unit/test_pedido_factura_documentos.py -q`: **25 passed**
- Vitest `AppLayout.comprasBanners.test.jsx`: deferred (no local `node_modules`/vitest in worktree); covered by file + CI

## Deviations from Design

- Alembic revision remains **`compras_044`** (PR1); no new migration in PR2.
- Snooze hide clock uses `fecha_creacion + 1h` as mark baseline (D-SNOOZE); marker in `notas_revision`.
- No email/Slack (in-app only).

## Remaining Tasks

- [ ] 3.1–3.4 PR3 Depósito
- [ ] 4.1–4.5 PR4 multi-OC
- [ ] 5.1 Verify docs / ERP untouched

## Workload / PR Boundary

- Mode: chained PR slice (feature-branch-chain)
- Current work unit: PR2 alerts 2.1–2.5
- Branch: `feat/compras-ops-pipeline-02-alerts` (base: `feature/compras-ux` / PR1)
- Boundary: in-app Notificacion fan-out + ok/snooze + AppLayout banners. Stops before Depósito UX / multi-OC.

## Attempt Settlement

- Token: `sha256:924960defc0dccbbcb00ab9a56d0e6bdd9cb829969816e864dd0f5146a20bc44`
- Request: `settle-pr2-alerts-01`
- Inventory (acquire): `sha256:e69e3fa6db66e358ea76b436641f90e7e20c7acd278d9d5e4a8368659106bacd` (will refresh on settle if drifted)

## Status

12/22 tasks complete. PR2 alerts ready as chained slice. Not ready for verify until Phases 3–5 land.
