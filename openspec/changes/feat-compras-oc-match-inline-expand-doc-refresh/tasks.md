# Tasks: feat-compras-oc-match-inline-expand-doc-refresh

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 250–450 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Under-row accordion + extract-only refresh | PR 1 | See DoD | N/A — no Gemini in browser | Revert design file list. Retry+checkbox, stamp, `apply_writeback`, `numero_factura` stay. No Alembic. |

## Phase 1: Branch

- [x] 1.1 Create `feat/compras-oc-match-inline-expand-doc-refresh` from `upstream/main` (not develop). Single PR to `main`.

## Phase 2: Backend persist (extract-only)

- [x] 2.1 Create `backend/app/services/oc_match/refresh_doc_refs.py`: `refresh_doc_refs_job(job_id)` two-session. S1: adjunto bytes if still `done`\|`error`. Close. `load_pool` + `extract_one` (no Session). Fail → leave stamp/job/pedido. S2 job `FOR UPDATE`; skip if status left; clear stamp; pedido `FOR UPDATE`; unchanged `apply_writeback`; restamp `datetime.now(UTC)` if True. Never `claim_queued_job` or `progress_phase`.
- [x] 2.2 Export `refresh_doc_refs_job` from `backend/app/services/oc_match/__init__.py`. Do not edit worker/enqueue/gemini_pool/doc_refs.

## Phase 3: Backend endpoint

- [x] 3.1 In `backend/app/routers/administracion_compras.py` add `POST /oc-match/jobs/{job_id}/refresh-doc-refs`: empty body; `gestionar_ordenes_compra`; reclaim + 404 helper; 409 unless `done`\|`error`; `add_task(refresh_doc_refs_job, job.id)`; 200 `OcMatchJobResponse` immediately; never `queue_retry`. Leave retry handler unchanged.

## Phase 4: Frontend DataTable expand

- [x] 4.1 In `frontend/src/components/compras/_shared/DataTable.jsx` add optional `expandedRowId` + `renderExpandedRow` (off unless both set). `Fragment` + `tr.expandedRow` / `td colSpan` + `stopPropagation` after matching row. Omitted props → unchanged markup.
- [x] 4.2 In `frontend/src/components/compras/_shared/DataTable.module.css` add `.expandedRow` with no hover/click accent; nested tables keep own hover. CF tokens only.

## Phase 5: Frontend TabOcMatch + hook

- [x] 5.1 In `frontend/src/hooks/useOcMatch.js` add `refreshDocRefs(id)` empty POST `${OC_MATCH_BASE}/${id}/refresh-doc-refs`. Do not add `done`\|`error` to `OC_MATCH_ACTIVE`. Keep `retry` + `refrescar_doc_refs`.
- [x] 5.2 In `frontend/src/components/compras/TabOcMatch.jsx` bind list `expandedRowId={selectedId}` + `renderExpandedRow` with existing `detailBody`. Same-row toggle; other row moves expand; pagination after table. No sibling below list; no aside/modal. Renglones omit expand.
- [x] 5.3 In `frontend/src/components/compras/TabOcMatch.jsx` add `Actualizar Factura/s y Pedido/s` in `.actions` iff `done`\|`error` + gestionar, **beside** Retry+checkbox (checkbox/flag untouched). Click → `refreshDocRefs`; banner `Actualización encolada` or `detail`; disable after enqueue; no Gemini spinner. Hide view-only and `queued`\|`running`\|`skipped`. No stamp.
- [x] 5.4 In `frontend/src/components/compras/TabOcMatch.module.css` add expand-cell / banner CF tokens. Keep `.checkboxLabel`.

## Phase 6: Tests

- [x] 6.1 Create `frontend/src/components/compras/_shared/DataTable.test.jsx`: omitted props unchanged; `colSpan` under matching row only.
- [x] 6.2 Update `frontend/src/components/compras/TabOcMatch.test.jsx`: under-row; toggle; no aside/modal; button `done`+gestionar; error keeps Retry+checkbox; hide view-only and `queued`\|`running`\|`skipped`; banner; no stamp. Keep retry checkbox.
- [x] 6.3 Update `frontend/src/hooks/useOcMatch.test.js`: `refreshDocRefs` POSTs `refresh-doc-refs`; poll stays false for `done`\|`error`. Keep retry payload tests.
- [x] 6.4 Create `backend/tests/unit/test_oc_match_refresh_doc_refs.py`: fail keeps stamp; skip if status left; success clears then write-back + restamp; never match/Excel/`queue_retry`/`numero_factura`/alerts.
- [x] 6.5 Update `backend/tests/integration/test_oc_match_enqueue.py`: 200 `done`+`error` status unchanged; 409 `queued`\|`running`\|`skipped`; 403 view-only; renglones/acta/`excel_rel_path` unchanged. Leave empty-POST retry.

## Definition of Done / Verification

Backend: `pytest tests/unit/test_oc_match_refresh_doc_refs.py tests/integration/test_oc_match_enqueue.py -q --tb=short`

Frontend: `pnpm exec vitest run src/components/compras/_shared/DataTable.test.jsx src/components/compras/TabOcMatch.test.jsx src/hooks/useOcMatch.test.js`

