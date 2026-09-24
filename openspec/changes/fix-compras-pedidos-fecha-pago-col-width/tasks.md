# Tasks: Shrink Pedidos Fecha pago column

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 15–40 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR to main |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Fecha pago 110px | PR 1 → main | `pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx` | N/A — jsdom col style; visual overlap is manual | Revert the three Pedidos files |

## Phase 1: Column width

- [x] 1.1 In `frontend/src/components/compras/TabPedidosCompra.jsx` set `COLUMNS` `fecha_pago` `width` to `'110px'`. Do not change `moneda` (`60px`), `estado` (`152px`), `proceso` (`220px`), or Proveedor (no width).
- [x] 1.2 Optional: in `frontend/src/components/compras/TabPedidosCompra.module.css` set `.badgeVenceUrgente` / `.badgeVencido` `margin-left: 0` so a wrapped badge sits under the date. Skip if wrap already looks flush.

## Phase 2: Cheap test

- [x] 2.1 In `frontend/src/components/compras/TabPedidosCompra.test.jsx` assert Fecha pago `<col>` width is `110px` and Estado / Proceso stay `152px` / `220px` (header index → `colgroup`). Skip Playwright.

## Definition of Done / Verification

`cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx`
