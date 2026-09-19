# Apply Progress: feat-compras-oc-match

**Change**: feat-compras-oc-match
**Mode**: Standard
**Slice**: Phase 4 / PR 4 UI (tasks 4.1–4.4); Phase 1–3 already landed
**Branch**: feat/compras-oc-match-04-ui
**Chain**: feature-branch-chain (PR 4 targets PR 3 `feat/compras-oc-match-03-pipeline` tip `e78cc1b9`)
**Hook**: WIRED (backend); UI polls GET list/detail every 3s while queued|running
**Workload**: size:exception — authored add+del ≈ **1091** (new files 1006 + tracked ~85) vs typical 800; tests+CSS+tab are one cohesive UI unit

## Completed Tasks

- [x] 1.1–1.8 Phase 1 Foundations (landed).
- [x] 2.1–2.5 Phase 2 Trigger (landed).
- [x] 3.1–3.5 Phase 3 Pipeline (landed).
- [x] 4.1 Add `frontend/src/hooks/useOcMatch.js`: list/detail/retry/excel; poll 3s while `queued|running`.
- [x] 4.2 Add `frontend/src/components/compras/TabOcMatch.jsx` + CSS Module: renglones/acta/download; retry iff `gestionar`.
- [x] 4.3 Register `TABS` `id: oc-match` in `AdministracionCompras.jsx` (`administracion.ver_ordenes_compra`).
- [x] 4.4 Tests `TabOcMatch.test.jsx` + `useOcMatch.test.js`: tab hidden without view; retry hidden view-only; poll stops on terminal.

## Work Unit Evidence (Phase 4)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm exec vitest run --project=unit src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.test.js` → **14 passed** in 2.53s (2 files) |
| Lint | `pnpm exec eslint` on touched JS/JSX → 0 errors; `stylelint TabOcMatch.module.css` → 0 errors |
| Runtime harness command/scenario and exact result | N/A in this worktree (no browser/dev server). Poll stop covered by fake timers in `useOcMatch.test.js`; tab/retry gates covered by RTL + mocked permisos. Deep-link `?tab=oc-match` uses existing TABS query support. |
| Rollback boundary | `useOcMatch.js`, `TabOcMatch.jsx` + module CSS + tests, TABS entry in `AdministracionCompras.jsx`, SDD tasks/apply-progress. Revert does not remove Phase 1–3 backend. |

## Implementation notes

- Hook owns list/detail/retry/blob excel + `setInterval(3000)` while selected or list has `queued|running`; cleanup on unmount and when `needsOcMatchPoll` is false.
- Retry button only if `tienePermiso('administracion.gestionar_ordenes_compra')` AND `job.retryable` or `status === 'error'`.
- Tab visibility via existing `TABS.filter(tienePermiso)` — no extra gate.
- CSS: CF tokens + `composes` from forms-tesla/buttons-tesla; no hex; lucide icons only.
- TABS not named-exported (react-refresh/only-export-components). Visibility tested by rendering `AdministracionCompras` with mocked permisos.

## Deviations from Design

None material. List+side detail panel instead of expand-row. Filter includes `skipped` (spec MAY).

## Remaining Tasks

None in Phase 4. Verify / PR open is out of this apply unit.

## Workload / PR Boundary

- Mode: chained PR slice with **size:exception**
- Current work unit: PR 4 UI
- Boundary: tab + hook + poll + TABS + focused FE tests
- Estimated review budget impact: authored add+del ≈ **1091** exceeds 800. Tests cannot be dropped; tab+hook+CSS+tests are one cohesive unit. Do not golf.
