# Tasks: Pedidos layout + factura-cargada alert ops

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 180–320 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR to main (stacked on #1347) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Layout + cron/ADMIN docs | PR 1 → main | `cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Playwright geometry at 1280–1400 | Revert Pedidos files + docs hunks |

## Phase 1: Pedidos layout

- [x] 1.1 In `frontend/src/components/compras/TabPedidosCompra.jsx` wrap Empresa in a cell class; show full `empresa_nombre`. Cap `COLUMNS.empresa.width` to **Pastoriza** (+ td pad). Do not change Fecha pago `110px`, Mon `60px`, Estado `152px`, Proceso `220px`, or Proveedor (no width).
- [ ] 1.2 In `frontend/src/components/compras/TabPedidosCompra.module.css`: no ellipsis. **Pastoriza** one line. **Grupo Gauss** only → **2 centered lines** inside Pastoriza width (do not force every empresa to 2 lines). (Gabe lock mid-apply)
- [x] 1.3 In `frontend/src/components/compras/TabPedidosCompra.module.css` make `.rowActions` a 2-column grid. In `frontend/src/components/compras/TabPedidosCompra.jsx` shrink `COLUMNS.acciones` below `180px` to the measured 2-icon width.

## Phase 2: Layout tests

- [x] 2.1 In `frontend/src/components/compras/TabPedidosCompra.test.jsx` keep Fecha pago `110px` and Estado/Proceso `152`/`220`. Assert Acciones `<col>` `< 180px`. Do not add a literal Empresa px assert.
- [x] 2.2 In `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` paint at 1280–1400 (not 1600). Fixtures `Grupo Gauss` and `Pastoriza`: full text, no ellipsis. Acciones two-column geometry. Proveedor/Mon overlap area 0.

## Phase 3: Alert ops docs

- [x] 3.1 In `docs/RUNBOOKS.md` add a short factura-cargada section: cron is required; command `python -m app.scripts.dispatch_factura_cargada_alerts`; 5m delay unchanged; empty `numero` is a no-op.
- [x] 3.2 In `docs/modulos/compras-post-deploy-checklist.md` add a crontab checkbox for that command (every minute).
- [x] 3.3 In `docs/modulos/compras-guia-usuario.md` (and optionally `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md`) state ADMIN role is not enough; recipients = `administracion.ver_alertas_factura`; Chicho assigns perms.
- [x] 3.4 If apply proves sweep unwired or empty-nº checkable: minimal fix in `backend/app/services/compras_alertas_service.py` or `backend/app/scripts/dispatch_factura_cargada_alerts.py` only. Otherwise skip Python.

## Definition of Done / Verification

`cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx`

Grep docs for `dispatch_factura_cargada_alerts` and `ADMIN`.
