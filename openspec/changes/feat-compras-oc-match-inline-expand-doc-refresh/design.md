# Design: feat-compras-oc-match-inline-expand-doc-refresh

## Technical Approach

Two surfaces, one PR. **FE:** optional DataTable expand (`expandedRowId` + `renderExpandedRow`) inserts a `colSpan` `<tr>` under the selected job; TabOcMatch moves `detailBody` there; pagination stays after the table. **BE:** `POST …/refresh-doc-refs` schedules extract-only `BackgroundTasks`. Never `queue_retry`, rematch, Excel, or mutate status / renglones / acta. JSON is not on the job → must `extract_one`. Clear `doc_refs_aplicado_at` only after successful extract, immediately before `apply_writeback`. Specs: MODIFY ui / jobs / pipeline.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| Expand | Shared slot vs fork vs CSS fake | Blast vs drift vs broken table | **Optional props, default off** |
| Same-row | Toggle vs stay | Accordion vs sticky | **Toggle** |
| API | New path vs retry `mode` | `queue_retry` needs `error` + sets `queued` | **Dedicated empty POST** |
| HTTP | Sync Gemini vs 200+task vs flip `queued` | Timeout / rematch UX | **200 `OcMatchJobResponse`; status unchanged** |
| Fence | `claim_queued_job` vs job `FOR UPDATE` | Claim flips `running` | **HTTP 409 + persist job `FOR UPDATE` + status still `done`/`error`** |
| Stamp | Enqueue vs after extract | Failed Gemini + default Retry | **Clear after extract, before write-back** |
| FE wait | Spinner vs banner | 503 can idle minutes | **“Actualización encolada”; HTTP-flight only** |

## Data Flow — refresh-doc-refs

```
HTTP Session
  reclaim_stale_running → 404 helper
  status ∉ {done, error} → 409
  add_task(refresh_doc_refs_job, id)
  200 OcMatchJobResponse          # no queue_retry

refresh_doc_refs_job              # NOT claim_queued_job
  S1 get_background_db:
    load job + adjunto
    status ∉ {done, error} → return
    read bytes + filename
  close
  extract_one(pool, bytes, name)  # no Session
  fail / missing file → log, return (stamp/job/pedido unchanged)
  S2:
    SELECT job FOR UPDATE
    status ∉ {done, error} → return   # retry claimed
    doc_refs_aplicado_at = None
    SELECT pedido FOR UPDATE
    apply_writeback (unchanged)
    if True: restamp datetime.now(UTC)
```

Never write `progress_phase`, `started_at`, status, renglones, acta, `excel_rel_path`, `numero_factura`, extract JSON, or alerts. Concurrent refreshes serialize on the job lock.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/_shared/DataTable.jsx` | Modify | Optional expand; `Fragment` + `colSpan` `tr.expandedRow` + `stopPropagation` |
| `frontend/src/components/compras/_shared/DataTable.module.css` | Modify | `.expandedRow` no hover/click accent; nested tables keep own hover |
| `frontend/src/components/compras/_shared/DataTable.test.jsx` | Create | Default-off; expand under matching row |
| `frontend/src/components/compras/TabOcMatch.jsx` | Modify | Expand + toggle; move `detailBody`; button + banner; keep Retry + checkbox |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modify | Expand-cell / banner CF tokens |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modify | Under-row; toggle; button gates; no stamp on detalle |
| `frontend/src/hooks/useOcMatch.js` | Modify | `refreshDocRefs(id)` empty POST; do not poll-as-running |
| `frontend/src/hooks/useOcMatch.test.js` | Modify | POST path; poll stays false for `done`/`error` |
| `backend/app/routers/administracion_compras.py` | Modify | Route; `gestionar`; reclaim; 409; `add_task`; never `queue_retry` |
| `backend/app/services/oc_match/refresh_doc_refs.py` | Create | `refresh_doc_refs_job` two-session persist |
| `backend/app/services/oc_match/__init__.py` | Modify | Export `refresh_doc_refs_job` |
| `backend/tests/unit/test_oc_match_refresh_doc_refs.py` | Create | Fail keeps stamp; skip if status left; no rematch/Excel |
| `backend/tests/integration/test_oc_match_enqueue.py` | Modify | 200 done/error; 409 queued/running/skipped; 403; columns unchanged |

Unchanged: `queue_retry`, `worker._persist`, `gemini_pool.py`, `apply_writeback`, DTO stamp, Alembic, other DataTable consumers.

## Interfaces / Contracts

```
POST /administracion/compras/oc-match/jobs/{job_id}/refresh-doc-refs
permiso: administracion.gestionar_ordenes_compra
body: empty
200 OcMatchJobResponse   # status unchanged
403 without gestionar
404 existing helper
409 after reclaim if status ∉ {done, error}
```

```js
refreshDocRefs(id) => api.post(`${OC_MATCH_BASE}/${id}/refresh-doc-refs`)
```

Label **Actualizar Factura/s y Pedido/s**. Banner **Actualización encolada**. Button iff `done`|`error` + gestionar. Keep error checkbox `También actualizar Factura/s y Pedido/s`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Extract fail keeps stamp; skip if queued; clear then writeback; never match/Excel/`queue_retry` | `test_oc_match_refresh_doc_refs.py` |
| Integration | 200 done+error; 409 queued/running/skipped; 403 view-only | `test_oc_match_enqueue.py` |
| Vitest | DataTable default-off + `colSpan`; TabOcMatch toggle / no aside / button / banner; hook no poll | `DataTable.test.jsx`, `TabOcMatch.test.jsx`, `useOcMatch.test.js` |
| E2E | N/A | No Gemini in browser |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR, executable-file, or process-integration boundary.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| DataTable blast | Props default off; scoped CSS; renglones stay `tables[1]` |
| Stamp cleared then Gemini fails | Clear only after successful extract |
| Retry during refresh | Persist no-op if status left `done`/`error` |
| Double POST / Gemini cost | Disable after enqueue; `append_unique` |
| TC-error looks like rematch | Stay `error`; dedicated label; no Excel |
| Ops-ux “below the list” | Specs renamed to under-row; keep no aside/modal |

## Out of Scope

Extract-JSON column / Alembic / stamp-on-detalle; Celery; Gemini backoff; wipe Factura/s · Pedido/s; `numero_factura`; alerts; MIME/enqueue/status CHECK; retry `mode`; flip `queued`/`running` or reuse `progress_phase`; TabOcMatch table fork; blocking Gemini spinner.

## Migration / Rollout / Rollback

No migration, no flag. Single PR `feat/compras-oc-match-inline-expand-doc-refresh` → `main` from `upstream/main` after parent retry-guard.

**Rollback:** drop DataTable expand props; restore sibling `detailBody`; delete route, `refresh_doc_refs.py`, hook, button, banner. Retry + checkbox, stamp, `apply_writeback`, `numero_factura` stay.

## Open Questions

None. Locks in `state.yaml`.
