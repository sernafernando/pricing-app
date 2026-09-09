# Tasks: Stable paging for Acciones masivas resolve

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–150 |
| 400-line budget risk | Low |
| Chained PRs recommended | No — push onto existing PR1 branch |
| Delivery strategy | single-pr (amend #1245) |

## Phase 1: Resolve hardening

- [x] 1.1 Add stable `orden_campos`/`orden_direcciones` in `buildListarParamsFromFiltros`; accumulate IDs via `Set`.
- [x] 1.2 Always enforce mismatch vs finite `totalProductos`; keep empty fail-closed only when filters active.
- [x] 1.3 Add `maxPages` ceiling; fail closed if exceeded.

## Phase 2: Tests

- [x] 2.1 Update/add Vitest: params include order; unfiltered mismatch; duplicate pages → mismatch; maxPages trip.
- [x] 2.2 Keep existing modal/resolve suites green.

## Phase 3: Delivery

- [ ] 3.1 Commit on `fix/markup-masivo-01-resolve-modal`, push, rebase PR2, reply to #1245 review.
