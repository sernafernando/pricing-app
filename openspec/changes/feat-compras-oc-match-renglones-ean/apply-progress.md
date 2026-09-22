# Apply Progress: feat-compras-oc-match-renglones-ean

**Change**: feat-compras-oc-match-renglones-ean
**Mode**: Standard
**Work unit**: renglones-ean-fe
**Branch**: `feat/compras-oc-match-renglones-ean` (from `upstream/main`)
**Updated**: 2026-09-21

## Completed Tasks

- [x] 1.1 Create `feat/compras-oc-match-renglones-ean` from `upstream/main`
- [x] 2.1 Lock `RENGLON_COLUMNS` order/labels/widths; bind `ean` not `ean_extract`
- [x] 2.2 Set renglones DataTable `minWidth` to `820px`; job-list unchanged
- [x] 3.1 Add module-level `formatCantidad` and `formatPrecioUnitario`
- [x] 3.2 Renglones `renderCell`: confianza badge, ean + `.tdMono`, descripcion truncate+title, formatters
- [x] 3.3 Add `.tdTruncate` in `TabOcMatch.module.css`; `.acta` untouched
- [x] 4.1 Fixture: matched EAN, null EAN, `2.0000` / `0.5000`, `12.3456`, `ean_extract` on payload
- [x] 4.2 Assert locked headers, EAN, em dash, unidades qty, 4dp precio
- [x] 4.3 Assert no `ean_extract` header; acta `<pre>` unchanged; Vitest run
- [x] 5.1 This apply-progress artifact

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/TabOcMatch.jsx` | Modified | `RENGLON_COLUMNS` lock + EAN; `minWidth` 820px; local formatters; renderCell |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modified | Added `.tdTruncate` only |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modified | Fixture + renglones EAN assertions |
| `openspec/changes/feat-compras-oc-match-renglones-ean/tasks.md` | Modified | Marked tasks `[x]` |
| `openspec/changes/feat-compras-oc-match-renglones-ean/state.yaml` | Modified | `ready_for_verify` / nextRecommended verify |

Read-only (not edited): `useOcMatch.js`, `DataTable.jsx`, `DataTable.module.css`, `.acta` rule, `frontend/src/novedades/2026-09-21-oc-match.md`.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx` — exit 0; Test Files 1 passed; Tests 11 passed (11); Duration 4.50s |
| Runtime harness command/scenario and exact result | N/A — no API/hook/runtime boundary; jsdom unit coverage only. Browser density check deferred to after apply. |
| Rollback boundary | Revert the three TabOcMatch files (`TabOcMatch.jsx`, `TabOcMatch.module.css`, `TabOcMatch.test.jsx`) plus this apply-progress. No backend/schema/hook changes. |

## Deviations from Design

None — implementation matches design.

## Issues Found

None.

## Workload / PR Boundary

- Mode: single PR
- Current work unit: renglones-ean-fe
- Boundary: branch from `upstream/main` through FE renglones EAN/order/format + Vitest
- Estimated review budget impact: within 40–120 forecast; under 200-line work-unit cap

## Status

10/10 tasks complete. Ready for verify.
