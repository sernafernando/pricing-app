# Apply Progress: fix-compras-pedidos-empresa-wrap

**Change**: fix-compras-pedidos-empresa-wrap
**Mode**: Standard (strict_tdd not enabled; no openspec/config.yaml tdd flag)
**Branch**: `feat/compras-pedidos-layout-y-alerta-factura`
**Delivery**: single-pr follow-up commit on #1348 → `main` (Low risk, Decision needed: No). Do not open a new PR. Do not commit in apply.
**Work unit**: `1` — Generic 2-line Empresa wrap

## Completed Tasks

- [x] 1.1 `case 'empresa'` renders `nombre` only. Removed `isGrupoGauss`, `<br>`, `data-wrap`, and extra class. Kept `data-testid="empresa-cell"`. `COLUMNS` untouched.
- [x] 1.2 Single locked `.empresaCell` (`white-space: normal`, `overflow-wrap: anywhere`, `max-height: 2.5em`, `overflow: hidden`, center). Deleted `.empresaCellGrupoGauss` and company-name comments.
- [x] 2.1 jsdom: two different raw names, no `<br>`, no `data-wrap`.
- [x] 2.2 Visual: shared locked computed style on every cell; two-word wrap + short one-line + long-name clip ≤2.5em; no ellipsis; no Proveedor overlap. Acciones / Fecha pago asserts not retuned.

## Work Unit Evidence

### Unit 1 — Generic 2-line Empresa wrap

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` → **18 passed** (2 files). Unit-only `--project=unit` → **17 passed**. |
| Runtime harness command/scenario and exact result | `cd frontend && pnpm exec vitest run --project=visual src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` → **1 passed** (Chromium). Host 1360px; shared locked style; two-word wrap without clip; short name one line; long name `scrollHeight > clientHeight` and height ≤ 2.5em; Proveedor overlap 0. |
| Rollback boundary | Revert `TabPedidosCompra.jsx`, `TabPedidosCompra.module.css`, `TabPedidosCompra.test.jsx`, and `tabPedidosCompraFechaPago.visual.test.jsx`. Do not revert Acciones / COLUMNS / backend. |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | Removed name regex / `<br>` / `data-wrap`; render raw `nombre` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified | Locked single `.empresaCell`; deleted `.empresaCellGrupoGauss` |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modified | Name-agnostic jsdom: raw names, no `br`, no `data-wrap` |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Modified | Generic clip fixtures; dropped `data-wrap` branch |
| `openspec/changes/fix-compras-pedidos-empresa-wrap/tasks.md` | Modified | All 4 tasks `[x]` |

## Deviations from Design

None — implementation matches design. Locked CSS copied as specified. `COLUMNS` unchanged. Acciones untouched. No backend change.

## Issues Found

None.

## Workload / PR Boundary

- Mode: single PR (follow-up commit on #1348; apply did not commit or open a PR)
- Current work unit: Generic 2-line Empresa wrap
- Boundary: planning-complete → this apply (JSX + CSS + unit + visual)
- Estimated review budget impact: Low (under 400 authored lines)

## Status

4/4 tasks complete. Ready for verify.
