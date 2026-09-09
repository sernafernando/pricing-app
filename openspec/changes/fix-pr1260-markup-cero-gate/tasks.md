# Tasks: PR #1260 Chicho review

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 40–90 |
| 400-line budget risk | Low |
| Chained PRs recommended | No — push onto #1260 branch |
| Delivery strategy | single-pr |

## Phase 1: Code + tests

- [x] 1.1 Modal gate `markup <= 0`; update Vitest zero ≤50 and zero+>50 stacking.
- [x] 1.2 Schema `ge=-100` + pytest accept −100 / reject below floor.
- [x] 1.3 Update PR #1260 body: `listarParams` (not `filtrosActivos`).

## Phase 2: Delivery

- [x] 2.1 Commit + push `fix/markup-masivo-02-wiring-desync`; reply to Chicho comment.
