# Exploration: Pedidos layout + factura-cargada alert ops

## Exploration: feat-compras-pedidos-layout-y-alerta-factura

### Current State

**A) Pedidos table.** `TabPedidosCompra.jsx` `COLUMNS` (fixed px unless noted):

| Col | Width | Notes |
|-----|-------|-------|
| Número | 160 | mono P-number |
| Empresa | 140 | raw `empresa_nombre`; no wrap class |
| Proveedor | *(flex)* | only uncapped col |
| Mon. | 60 | locked |
| Saldo | 180 | dual-line already |
| Plazo | 120 | already capped |
| Fecha pago | 110 | locked #1347; badge wraps |
| Estado | 152 | locked |
| Proceso | 220 | locked |
| Acciones | 180 | `.rowActions` flex row of icon buttons |

Fixed sum ≈ **1322px** before Proveedor. Visual test wraps the table at **1600px** so leftover exists — that hides the 1280–1400 squeeze Chicho hit. `DataTable` is `table-layout: fixed`; `th` is `nowrap` + 16px pad. `td` has no ellipsis; overflow is horizontal scroll + painted collision (Proveedor/Mon. after #1344).

**B) Factura cargada alert.** Code already matches Gabe locks:

- Recipients = `resolver(administracion.ver_alertas_factura)` only. Catalog seed `compras_046` assigns **no default roles**. ADMIN role alone is out.
- Check sets `alerta_pendiente_hasta = now + 5m`. Uncheck nulls it.
- Fire = `disparar_alertas_factura_pendientes` via `python -m app.scripts.dispatch_factura_cargada_alerts`.
- Copy uses `pedido.numero` (P-number) + `pedido_factura_documentos.numero` (supplier invoice). Empty invoice nº → notify **no-op**.
- Sweep still stamps `alerta_disparada_at` after the no-op (no retry loop). Persist/Match never notify.

**Ops gap:** cron lives only in the script docstring. Missing from `docs/RUNBOOKS.md`, `docs/modulos/compras-post-deploy-checklist.md`, and `backend/CRON_COMPLETO_OPTIMIZADO.md`. Guía mentions the permiso but not “ADMIN role is not enough” or “cron must run”. No health endpoint for last sweep — other Compras crons are also docs-only.

Chicho assigns perms in DB — **out of code scope**.

### Affected Areas

- `frontend/src/components/compras/TabPedidosCompra.jsx` — Empresa cell, Acciones grid, COLUMNS widths
- `frontend/src/components/compras/TabPedidosCompra.module.css` — empresa wrap, `.rowActions` 2×2
- `frontend/src/components/compras/TabPedidosCompra.test.jsx` — keep/soften 110px; avoid new brittle px
- `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` — geometry at 1280–1400
- `docs/RUNBOOKS.md`, `docs/modulos/compras-guia-usuario.md`, `docs/modulos/compras-post-deploy-checklist.md` — cron + ADMIN note
- `backend/app/scripts/dispatch_factura_cargada_alerts.py` — already wired; docs consume it
- `backend/app/services/compras_alertas_service.py` — only if empty-nº / sweep gap found

Unchanged: DataTable shared padding, TabOcMatch, backend pricing, #1347 merge.

### Approaches

1. **Layout via cell CSS + COLUMNS rebalance (recommended)** — 2-line centered Empresa (no ellipsis), Acciones CSS grid 2 cols, shrink those two widths, keep locked cols, Proveedor stays flex.
   - Pros: local to Pedidos; no DataTable API change
   - Cons: apply must measure Empresa cap (Grupo Gauss / Pastoriza)
   - Effort: Low–Medium

2. **TanStack column sizing** — overkill vs existing `<colgroup>`.
   - Effort: High

3. **Alert: docs-only cron + ADMIN note (recommended)** — script already wired; add RUNBOOKS / post-deploy / guía.
   - Pros: matches “verify cron is required”
   - Cons: does not auto-install crontab
   - Effort: Low

4. **Alert: add health/last-sweep metric** — only if apply proves sweep never invoked in prod path. Today it is a standard `python -m` cron like other scripts.
   - Effort: Medium; defer unless gap confirmed

### Recommendation

Do A+B in **one** follow-up stacked on #1347 tip. Layout = approach 1. Alerts = approach 3; touch Python only if apply finds a real no-op/sweep bug. Do not merge #1347 here.

### Risks

- DataTable `th` nowrap + 16px pad: Empresa header is short (`EMPRESA`); Acciones header is empty — OK
- More than 4 action buttons: 2-col grid grows rows, not width
- jsdom `css: false`: painted geometry needs Playwright visual, not more `<col>` px
- Main `compras-pipeline-alerts` spec still has stale UNION recipients; chicho-review-fixes delta is unarchived — this change ADDs cron/ops, does not re-MODIFY recipients

### Ready for Proposal

Yes — Gabe locks are complete. No open product questions.
