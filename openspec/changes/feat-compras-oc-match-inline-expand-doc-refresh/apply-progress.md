# Apply Progress: feat-compras-oc-match-inline-expand-doc-refresh

**Change**: feat-compras-oc-match-inline-expand-doc-refresh
**Mode**: Standard
**Branch**: `feat/compras-oc-match-inline-expand-doc-refresh` from `upstream/main` (`9cea7805`)
**Delivery**: single-pr → `main`

## Completed Tasks

- [x] 1.1 Branch from `upstream/main`
- [x] 2.1 `refresh_doc_refs.py` two-session persist
- [x] 2.2 Export `refresh_doc_refs_job`
- [x] 3.1 `POST …/refresh-doc-refs`
- [x] 4.1 DataTable expand slot
- [x] 4.2 DataTable `.expandedRow` CSS
- [x] 5.1 `useOcMatch.refreshDocRefs`
- [x] 5.2 TabOcMatch accordion under row
- [x] 5.3 Dedicated button + banner (Retry+checkbox untouched except placement)
- [x] 5.4 TabOcMatch expand/banner CSS
- [x] 6.1 `DataTable.test.jsx`
- [x] 6.2 `TabOcMatch.test.jsx`
- [x] 6.3 `useOcMatch.test.js`
- [x] 6.4 `test_oc_match_refresh_doc_refs.py`
- [x] 6.5 `test_oc_match_enqueue.py`

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | Backend: `pytest tests/unit/test_oc_match_refresh_doc_refs.py tests/integration/test_oc_match_enqueue.py -q --tb=short` → **24 passed** in 7.62s. Frontend: `pnpm exec vitest run src/components/compras/_shared/DataTable.test.jsx src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.test.js` → **37 passed** (3 files) in 3.84s |
| Runtime harness command/scenario and exact result | N/A — no Gemini in browser; pytest + jsdom |
| Rollback boundary | Drop DataTable expand props; restore sibling `detailBody`; delete route, `refresh_doc_refs.py`, hook, button, banner. Retry + checkbox, stamp, `apply_writeback`, `numero_factura` stay. No Alembic. |

## Deviations from Design

None. DataTable hover selector tightened to `tr:hover > td` so the expand cell does not paint nested renglones. Persist still clears stamp only after successful extract, immediately before `apply_writeback`.

## Issues Found

None.

## Status

15/15 tasks complete. Ready for verify.
