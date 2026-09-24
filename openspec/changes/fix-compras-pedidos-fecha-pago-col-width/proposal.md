# Proposal: Shrink Pedidos Fecha pago column

## Intent

After #1344 chip widths, Pedidos columns **Proveedor** and **Mon.** overlap. Fecha pago is oversized (`160px`) for `dd/mm/yyyy`. Shrink that column so Proveedor can flex without touching estado/proceso.

## Scope

### In Scope

- Pedidos table only (`TabPedidosCompra` `COLUMNS.fecha_pago`)
- Target width ~100–110px; lock **110px** (header `FECHA PAGO` nowrap + 16px padding)
- Urgency badge MAY wrap under the date (existing `.fechaPagoCell` wrap)
- Optional CSS so wrapped badge does not stay indented
- Cheap vitest on `<col>` width if cheap

### Out of Scope

- Backend, chip colors, other Compras tabs
- Estado / Proceso widths (`152px` / `220px`)
- Mon. width (`60px`), DataTable shared padding/API
- Playwright visual suite (chip tests stay as-is)

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `pedidos-compra`: Pedidos Fecha pago column MUST be date-sized (~110px); Proveedor/Mon. MUST NOT collide; estado/proceso widths MUST NOT grow

## Approach

Change `COLUMNS` `fecha_pago` `width` from `160px` to `110px`. Keep badge wrap. Do not expand estado/proceso.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | `fecha_pago` width `160px` → `110px` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified (optional) | Badge indent when wrapped |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modified | Assert col widths |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Header `FECHA PAGO` clips under 110px | Med | Lock 110px, not 100px; do not change DataTable nowrap |
| Badge `Vencido Nd` wider than date | Low | Existing `flex-wrap: wrap` |
| jsdom cannot prove painted overlap | Low | Assert `<col>` widths; visual check at apply |

## Rollback Plan

Revert the Pedidos `COLUMNS` / CSS / test lines. No schema, no API.

## Dependencies

Merged #1344 chip-width baseline on `main`. Branch: `feat/compras-pedidos-fecha-pago-col-width`. PRs target **main**.

## Success Criteria

- [ ] Fecha pago column width is `110px`
- [ ] Proveedor and Mon. no longer overlap
- [ ] Estado `152px` and Proceso `220px` unchanged
- [ ] Date still `dd/mm/yyyy`; badge may wrap under the date
