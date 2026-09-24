# Proposal: Pedidos layout + factura-cargada alert ops

## Intent

#1347 follow-up: Pedidos wastes width (Empresa 140, Acciones 180-row) so Proveedor/Mon. collide near 1280–1400. Factura alerts look dead if crontab is missing or ADMIN is assumed enough. Same PR.

## Scope

### In Scope

- Empresa: **no ellipsis**; width cap = **Pastoriza**; **Grupo Gauss** only wraps **2 centered lines**
- Acciones: **2×2 icon grid**; shrink ~180px col
- Keep Fecha pago 110, Mon 60, Estado 152, Proceso 220; Proveedor stays flex
- Tests: geometry/visual; keep 110px Fecha pago `<col>`
- Document cron `python -m app.scripts.dispatch_factura_cargada_alerts`
- Python only if apply finds a real sweep / empty-nº gap
- Docs: ADMIN role alone is not enough

### Out of Scope

- Merging #1347; TabOcMatch expand; backend pricing math
- Reassigning user permissions in DB (Chicho)
- Changing the 5-minute delay product lock

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `pedidos-compra`: Empresa 2-line full name; Acciones 2×2; column budget fits ~1280–1400
- `compras-pipeline-alerts`: factura-cargada fire requires deploy cron; ops/docs say ADMIN role is insufficient

## Approach

Cell CSS + `COLUMNS` widths on Pedidos only. Leave DataTable padding/API alone. Alert work is ops docs first; Python only for a proven gap.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `TabPedidosCompra.jsx` / `.module.css` | Modified | Empresa cell, Acciones grid, widths |
| `TabPedidosCompra.test.jsx` | Modified | Keep 110px; no new brittle px |
| `tabPedidosCompraFechaPago.visual.test.jsx` | Modified | Geometry at 1280–1400 |
| `docs/RUNBOOKS.md`, compras guía/checklist | Modified | Cron + ADMIN note |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Empresa cap too tight for a third legal name | Low | Cap = max(Grupo Gauss wrapped, Pastoriza) + td pad |
| Acciones >4 buttons | Low | Extra rows, still 2 columns |
| Cron documented but never installed | Med | RUNBOOKS + post-deploy checkbox |
| jsdom cannot prove wrap/overlap | Med | Playwright geometry; keep 110px `<col>` only |

## Rollback Plan

Revert Pedidos layout/CSS/tests and the docs hunks. No Alembic. No crontab uninstall unless we added one (we will not).

## Dependencies

Stacked on `feat/compras-pedidos-fecha-pago-col-width` tip (#1347 still open, do not merge). PRs target **main**.

## Success Criteria

- [ ] ~1280–1400 useful width: Proveedor/Mon. do not collide; table uses leftover
- [ ] Empresa shows full Grupo Gauss / Pastoriza, 2-line centered, no ellipsis
- [ ] Acciones is 2-col icon grid; col narrower than 180px
- [ ] Fecha pago stays 110px; Estado 152; Proceso 220; Mon 60
- [ ] Deploy docs name the factura-cargada cron; ADMIN-alone caveat written
