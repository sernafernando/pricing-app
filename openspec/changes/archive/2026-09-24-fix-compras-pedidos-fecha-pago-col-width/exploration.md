# Exploration: Pedidos Fecha pago column width

## Current State

After #1344 chip widths, Pedidos `DataTable` (`table-layout: fixed`, `minWidth="1100px"`) keeps `fecha_pago` at `160px` while `moneda` is already `60px` and `proveedor` has no width (flex). Proveedor and Mon. collide.

`fecha_pago` cell max text is `dd/mm/yyyy` via `formatDate`. Urgency badge (Clock + `7d` / `Hoy` / `Vencido Nd`) lives in `.fechaPagoCell { flex-wrap: wrap }` and MAY wrap under the date. Estado `152px` and Proceso `220px` must stay.

`DataTable` applies `col.width` on `<col>`. `th` is `10px` uppercase + `letter-spacing: 0.08em` + `white-space: nowrap` + `padding: 4px 16px`. `td` padding is `8px 16px`. At 100px, content box (~68px) likely clips header `FECHA PAGO` and the date. **110px** (top of Gabe 100–110 range) leaves ~78px for text.

No column-width tests today. jsdom `css: false` cannot prove painted overlap; `<col style="width">` is assertable. Visual Playwright exists only for chip colors.

## Affected Areas

- `frontend/src/components/compras/TabPedidosCompra.jsx` — `COLUMNS` `fecha_pago` width
- `frontend/src/components/compras/TabPedidosCompra.module.css` — optional wrap/badge indent
- `frontend/src/components/compras/TabPedidosCompra.test.jsx` — cheap col-width assert
- `frontend/src/components/compras/_shared/DataTable.jsx` — read-only; do not change shared padding

## Approaches

1. **Shrink `COLUMNS` width to 110px** — one-line `160px` → `110px`; badge wrap already exists
   - Pros: smallest diff; frees ~50px for Proveedor; stays in Gabe range
   - Cons: 110px is tight vs 16px cell padding; header may still feel snug
   - Effort: Low

2. **100px + DataTable per-column padding** — narrower col, new DataTable API
   - Pros: more room for Proveedor
   - Cons: shared-table change; out of scope; header nowrap will clip
   - Effort: Medium

3. **Widen estado/proceso or shrink Mon.** — move collision elsewhere
   - Pros: none vs locked product
   - Cons: Gabe forbids expanding estado/proceso; Mon. already 60px
   - Effort: Low (wrong)

## Recommendation

Approach 1: set `fecha_pago` to **`110px`**. Optional CSS: `margin-left: 0` on urgency badges so wrap is flush under the date. Do not change DataTable, estado, proceso, moneda, or backend.

## Risks

- Header `FECHA PAGO` nowrap + 16px padding may clip below ~110px
- jsdom cannot prove Proveedor/Mon. painted overlap; col style + visual check at apply is enough
- Badge `Vencido Nd` is wider than the date; wrap is required and already implemented

## Ready for Proposal

Yes — product locked by Gabe; no open decisions.
