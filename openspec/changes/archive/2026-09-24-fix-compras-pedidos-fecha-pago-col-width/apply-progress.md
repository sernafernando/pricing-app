# Apply Progress: fix-compras-pedidos-fecha-pago-col-width

**Change**: fix-compras-pedidos-fecha-pago-col-width
**Mode**: Standard (strict_tdd not enabled; no openspec/config.yaml tdd flag)
**Branch**: `feat/compras-pedidos-fecha-pago-col-width`
**Delivery**: single-pr → `main` (Low risk, Decision needed: No)
**Work unit**: `remediate-badge-and-overlap-evidence`
**Remediates**: `sha256:13f6a7ffceacc189619f0583fe56242204c41c963e626b2924f36506dc3f0475`

## Completed Tasks

- [x] 1.1 `COLUMNS.fecha_pago.width` `'160px'` → `'110px'`. Unchanged: moneda `60px`, estado `152px`, proceso `220px`, Proveedor no width.
- [x] 1.2 `.badgeVenceUrgente` / `.badgeVencido` `margin-left: 0` so a wrapped badge sits under the date.
- [x] 2.1 Vitest: Fecha pago `<col>` is `110px`; Estado `152px`; Proceso `220px` (header index → colgroup).
- [x] 3.1 Vitest: `aprobado` + `fecha_pago_estimada` within 7 days (and Hoy / Vencido) → `dd/mm/yyyy` + badge; Fecha pago `<col>` still `110px`.
- [x] 3.2 Playwright visual: Proveedor and Mon. cells have positive painted width and zero overlap area.

## Work Unit Evidence

### Unit 1 — apply-fecha-pago-110px (prior)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx` → **13 passed** (1 file) at apply |
| Runtime harness command/scenario and exact result | N/A — jsdom `css: false`; no painted overlap/layout runtime. Visual Proveedor/Mon. collision remained manual. |
| Rollback boundary | Revert `TabPedidosCompra.jsx` width, `TabPedidosCompra.module.css` badge margin, and the col-width describe in `TabPedidosCompra.test.jsx`. DataTable untouched. |

### Unit 2 — remediate-badge-and-overlap-evidence (this batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm --dir frontend exec vitest run src/components/compras/TabPedidosCompra.test.jsx` → **16 passed** (1 file; +3 badge/date cases). ESLint on both new/changed test files: EXIT 0. |
| Runtime harness command/scenario and exact result | `pnpm --dir frontend exec vitest run --project=visual src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` → **1 passed** (Chromium). Host 1600px so flexible Proveedor has leftover vs ~1322px fixed cols; asserts painted ink + cell boxes do not overlap Mon. |
| Rollback boundary | Revert the badge/date `it.each` in `TabPedidosCompra.test.jsx` and delete `tabPedidosCompraFechaPago.visual.test.jsx`. No production files in this unit. |

## TDD Cycle Evidence (optional; standard mode)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 / 1.1 | `TabPedidosCompra.test.jsx` | Unit | ✅ 12/12 | ✅ Expected 110px received 160px (13 tests, 1 failed) | ✅ 13/13 after width + CSS | ➖ Single scenario (col widths only) | ➖ None needed |
| 3.1 | `TabPedidosCompra.test.jsx` | Unit | ✅ 16/16 | ➖ Remediation added tests against already-green 110px + badge render | ✅ 16/16 (`3d` / `Hoy` / `Vencido 2d` + `dd/mm/yyyy` + col 110px) | ✅ Three badge variants | ➖ None needed |
| 3.2 | `tabPedidosCompraFechaPago.visual.test.jsx` | Visual | ✅ 1/1 | ✅ First run: proveedor `td` width 0 at 1280 viewport (fixed cols ~1322px) | ✅ 1/1 after 1600px host + painted-ink box | ➖ Single geometry scenario | ➖ None needed |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified (prior) | `fecha_pago` width `160px` → `110px` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified (prior) | Badge `margin-left: 0` |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modified | Col-width assert (prior) + badge/date `it.each` (3.1) |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Created | Playwright Proveedor/Mon. zero-overlap (3.2) |
| `openspec/changes/fix-compras-pedidos-fecha-pago-col-width/tasks.md` | Modified | Phase 3 added; 3.1 and 3.2 marked `[x]` |

## Deviations from Design

Original design left painted overlap as a manual check and said "no new Playwright". Phase 3 remediates failed verify (`UNTESTED` badge-wrap, `PARTIAL` no-collide) with a cheap vitest plus a Chromium visual, matching `tabPedidosCompraChips.visual.test.jsx` (`useSearchParams` mock, not MemoryRouter). Production CSS/JS unchanged in this unit.

## Issues Found

At the visual project's 1280×800 viewport, specified Pedidos column widths already sum ~1322px, so the flexible Proveedor `<td>` can measure 0. The visual host is 1600px so Proveedor has leftover; overlap is asserted on both cell boxes and painted ink.

## Workload / PR Boundary

- Mode: single PR
- Current work unit: remediate-badge-and-overlap-evidence
- Boundary: failed verify `sha256:13f6a7ffceacc189619f0583fe56242204c41c963e626b2924f36506dc3f0475` → this remediation commit (badge unit + visual no-collide)
- Estimated review budget impact: well under 150/400 for this unit

## Status

5/5 tasks complete. Ready for verify.
