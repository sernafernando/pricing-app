# Apply Progress: fix-markup-masivo-filtro

**Mode**: Standard (strict_tdd not enabled)
**Batch**: Work Unit 2 / PR2 slice (base = PR1 / WU1)
**Attempt token**: `sha256:ec0846ce10b7df7f5fc3dcd70be7838e8e1ed729e1ac3b5ad3bf6510b1ac4d58`
**Chain strategy**: feature-branch-chain
**Date**: 2026-09-04

## Cumulative completed tasks

### WU1 (prior batch)
- [x] 1.1 Shared resolve helper pages filtered `productosAPI.listar`
- [x] 1.2 Fail-closed empty/mismatch when filters active
- [x] 2.1 Modal props `filtrosActivos` + `totalProductos`
- [x] 2.2 Removed página-actual / visibles-only copy
- [x] 2.3 Tesla in-modal confirm when resolved count > 50; skip ≤ 50 (AGENTS: no `window.confirm`)
- [x] 2.4 Resolve into modal-local state; chunk 100 to existing endpoints
- [x] 4.1 Modal/resolve tests (18 / 200 / unfiltered N)
- [x] 4.2 Confirm / fail-closed / chunk tests
- [x] 5.2 Header/CTA/info copy uses Total / filter set

### WU2 (this batch)
- [x] 3.1 Productos wiring: `filtrosActivos` + `totalProductos`; open = `setMostrarMarkupMasivoModal(true)` only (no `cargarProductos`/`setProductos`); button title says conjunto filtrado
- [x] 3.2 Request-generation guard on `cargarProductos` / `cargarStats` via `latestProductosRequestRef` / `latestStatsRequestRef`
- [x] 4.3 `useProductosData.test.js` — stale listar/stats ignored
- [x] 4.4 Productos open→Cancelar smoke — no extra listar/stats; Total stays 18
- [x] 5.1 Confirmed: no edits to backend pricing/productos_* endpoints or Calcular Web/PVP components

## Remaining Tasks

None — all tasks.md checkboxes complete. Ready for verify.

## Work Unit Evidence (WU2)

| Evidence | Result |
|----------|--------|
| Focused test command | `cd frontend && pnpm exec vitest run --project=unit src/hooks/useProductosData.test.js src/pages/Productos.test.jsx -t "desync guard\|Acciones masivas open"` → **3 passed / 21 skipped**, exit 0 |
| Runtime harness | N/A — Vitest covers stale race + open/cancel; no separate Playwright boundary in this change |
| Rollback boundary | Revert `useProductosData.js` (+test), `Productos.test.jsx` smoke block, and the Acciones masivas title tweak in `Productos.jsx` (props wiring lands with PR1) |

## Authored line budget (WU2 focus)

| Path | Additions+deletions (approx) |
|------|------------------------------|
| `useProductosData.js` | ~14 |
| `useProductosData.test.js` (new) | ~177 |
| `Productos.test.jsx` (smoke) | ~52 |
| `Productos.jsx` (title + WU1 props vs HEAD) | props mostly WU1; WU2 title ~2 |
| **WU2-authored estimate** | **~245** (under 400) |

## Deviations from Design

None — generation guard matches VentasML / DivergenciasML `latestRequestRef` pattern.

## Issues

None.

## Workload / PR Boundary

- Mode: chained PR slice (feature-branch-chain)
- Current work unit: WU2 — Productos props confirm + listar/stats desync guard + tests
- Boundary: starts after WU1 (resolve helper + modal); ends when buffer/stats cannot desync and open/cancel preserves Total
- Next: sdd-verify (then child PR #2 targeting PR1 branch)
