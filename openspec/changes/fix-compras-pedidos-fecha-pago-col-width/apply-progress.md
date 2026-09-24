# Apply Progress: fix-compras-pedidos-fecha-pago-col-width

**Change**: fix-compras-pedidos-fecha-pago-col-width
**Mode**: Standard (strict_tdd not enabled; no openspec/config.yaml tdd flag)
**Branch**: `feat/compras-pedidos-fecha-pago-col-width`
**Delivery**: single-pr → `main` (Low risk, Decision needed: No)
**Work unit**: `apply-fecha-pago-110px`

## Completed Tasks

- [x] 1.1 `COLUMNS.fecha_pago.width` `'160px'` → `'110px'`. Unchanged: moneda `60px`, estado `152px`, proceso `220px`, Proveedor no width.
- [x] 1.2 `.badgeVenceUrgente` / `.badgeVencido` `margin-left: 0` so a wrapped badge sits under the date.
- [x] 2.1 Vitest: Fecha pago `<col>` is `110px`; Estado `152px`; Proceso `220px` (header index → colgroup).

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx` → **13 passed** (1 file) |
| Runtime harness command/scenario and exact result | N/A — jsdom `css: false`; no painted overlap/layout runtime. Visual Proveedor/Mon. collision remains manual. |
| Rollback boundary | Revert `TabPedidosCompra.jsx` width, `TabPedidosCompra.module.css` badge margin, and the col-width describe in `TabPedidosCompra.test.jsx`. DataTable untouched. |

## TDD Cycle Evidence (optional; standard mode)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 / 1.1 | `TabPedidosCompra.test.jsx` | Unit | ✅ 12/12 | ✅ Expected 110px received 160px (13 tests, 1 failed) | ✅ 13/13 after width + CSS | ➖ Single scenario (col widths only) | ➖ None needed |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | `fecha_pago` width `160px` → `110px` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified | Badge `margin-left: 0` |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modified | Assert Fecha pago / Estado / Proceso col widths |
| `openspec/changes/fix-compras-pedidos-fecha-pago-col-width/tasks.md` | Modified | Marked 1.1, 1.2, 2.1 `[x]` |

## Deviations from Design

None — implementation matches design.

## Issues Found

None. Painted Proveedor/Mon. overlap cannot be proven in jsdom; left as manual check for verify.

## Workload / PR Boundary

- Mode: single PR
- Current work unit: apply-fecha-pago-110px
- Boundary: planning commit `3f54ba17` → this apply commit ( Pedidos COLUMNS + badge CSS + col-width test )
- Estimated review budget impact: well under 150/400

## Status

3/3 tasks complete. Ready for verify.
