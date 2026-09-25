# Tasks: Generic Empresa two-line wrap

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 40–90 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | one follow-up commit on #1348 → main |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Generic 2-line Empresa wrap | follow-up on #1348 | `cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Playwright visual at 1360 | Revert the three Pedidos files |

## Phase 1: Remove name branch

- [x] 1.1 In `frontend/src/components/compras/TabPedidosCompra.jsx` `case 'empresa'`: render `nombre` only. Remove `isGrupoGauss`, `<br>`, `data-wrap`, and `.empresaCellGrupoGauss`. Keep `data-testid="empresa-cell"`. Do not edit `COLUMNS`.
- [x] 1.2 In `frontend/src/components/compras/TabPedidosCompra.module.css` replace `.empresaCell` and delete `.empresaCellGrupoGauss` with the locked CSS (`white-space: normal`, `overflow-wrap: anywhere`, `max-height: 2.5em`, `overflow: hidden`, center). Remove comments that name a company.

## Phase 2: Prove generic clip

- [x] 2.1 In `frontend/src/components/compras/TabPedidosCompra.test.jsx` assert empresa cells show the raw name, have no `<br>`, and have no `data-wrap` (jsdom; spec scenario “Wrap rule is name-agnostic”).
- [x] 2.2 In `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` drop `data-wrap` / `nowrap` branch asserts. Assert every empresa cell shares the locked computed style. Keep a two-word + a short-name fixture as wrap-vs-fit examples. Add a long-name fixture that clips at ≤2.5em with no ellipsis and no Proveedor overlap (scenarios: two-word wrap, short name one line, long name clips).

## Definition of Done / Verification

`cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx`

Do not retune Acciones or Fecha pago asserts. Do not open a new PR.
