# Proposal: feat-compras-oc-match-inline-expand-doc-refresh

## Intent

Live OC Match still drops operators below the full job list to see renglones/acta, and there is no way to re-extract Factura/s · Pedido/s without a full rematch + Excel. This change (1) expands job detail as an accordion **under the selected row** and (2) adds a dedicated extract-only refresh that re-runs Gemini `extract_one` + `apply_writeback` without rematch, Excel, or job-status mutation. Error-job **Reintentar** + checkbox `refrescar_doc_refs` stays.

## Scope

### In Scope

- Shared `DataTable` optional expand slot (`expandedRowId` + `renderExpandedRow`) inserting a `colSpan` row under the matching job `<tr>`. Default off — other compras tables unchanged.
- TabOcMatch moves existing `detailBody` into that slot. Click selected row toggles collapse; click another row moves the expand. Pagination stays after the table. No aside, no modal, full-width renglones.
- Dedicated `POST /administracion/compras/oc-match/jobs/{job_id}/refresh-doc-refs` (empty body). Permiso `administracion.gestionar_ordenes_compra`. **409** unless status is `done` or `error` (after reclaim). **409** on `queued` | `running` | `skipped`.
- HTTP returns immediately (non-blocking). BackgroundTasks two-session path: claim adjunto → close session → `extract_one` → persist session: on success clear `doc_refs_aplicado_at` → `SELECT FOR UPDATE` pedido → `apply_writeback` → restamp if routeable.
- Must **not** call `queue_retry`; must **not** rematch; must **not** regenerate Excel; must **not** mutate job status / renglones / acta / `excel_rel_path`. Must **not** write `numero_factura`. No alerts.
- FE button **Actualizar Factura/s y Pedido/s** on detail for `done` | `error` when the user has `gestionar`. Async: banner “Actualización encolada” / error `detail`; no blocking spinner until Gemini finishes.
- Keep existing error **Reintentar** + checkbox `refrescar_doc_refs` for full rematch.
- Single PR to `main` from `feat/compras-oc-match-inline-expand-doc-refresh` based on `upstream/main`.

### Out of Scope

- Persist extract JSON on the job (Gabe locked extract required because JSON is not stored).
- Expose `doc_refs_aplicado_at` on detalle / list DTO in this PR.
- Blocking spinner until Gemini finishes.
- Celery; Gemini backoff retune; wipe Factura/s · Pedido/s; change MIME/enqueue; widen status CHECK.
- Reuse `POST …/retry` with a `mode` / `solo_doc_refs` flag.
- Flip job to `queued`/`running` or reuse `progress_phase` (`extracting|matching|excel`).
- TabOcMatch-only forked `<table>`; CSS-only fake “under row”; non-table accordion list.
- Alerts / notificaciones from doc-refs refresh.

## Approach

Two locked surfaces, one PR.

**Expand (E1).** Add optional DataTable props. After the matching data `<tr>`, render:

```jsx
<tr className={styles.expandedRow} onClick={stopPropagation}>
  <td colSpan={columns.length}>{renderExpandedRow(row)}</td>
</tr>
```

TabOcMatch binds `expandedRowId` to the selected job and renders the existing detail card in `renderExpandedRow`. Nested renglones `DataTable` stays inside the expand cell. Expand-row CSS must disable hover/click accent so nested tables do not inherit list-row behavior.

This **MODIFIES** the ops-ux UI lock `detail_ux: expand_below_full_width` → accordion under the selected row. Keep: no aside, no modal, full-width renglones, CF tokens, `administracion.ver_ordenes_compra` to view.

**Dedicated refresh (A1 + B1).** New route, empty body, same permiso as retry. Eligibility is exclusive: `done` | `error` only. Does not call `queue_retry` (which requires `error` and sets `queued`). Background path mirrors the worker’s two-session pattern so Gemini never holds a request `Session`:

1. Short session: load adjunto bytes; confirm status still `done`|`error`.
2. Close session; `extract_one` (no Session).
3. Persist session **only if extract succeeded**: set `doc_refs_aplicado_at = None`, `SELECT FOR UPDATE` pedido, `apply_writeback` (unchanged, append-only unique), restamp if routeable. Skip write-back if status is no longer `done`|`error` (retry already claimed). Failed Gemini leaves stamp, job, and pedido unchanged.

Error jobs (including TC/`RechazoExcel` that already wrote tokens) may refresh numbers; the job **stays** `error`. Full rematch remains Retry + optional checkbox.

View-only (`ver_ordenes_compra`): hide the dedicated button. Backend still 403 without `gestionar`.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `compras-oc-match-ui`: accordion under selected row (replaces “below the entire list”); dedicated **Actualizar Factura/s y Pedido/s** on `done`|`error` + gestionar; keep error Retry + `refrescar_doc_refs` checkbox; async enqueue banner, no blocking Gemini spinner; do not show `doc_refs_aplicado_at` on detalle.
- `compras-oc-match-jobs`: new `POST …/oc-match/jobs/{job_id}/refresh-doc-refs`; empty body; `gestionar_ordenes_compra`; 409 unless `done`|`error`; 409 on `queued`|`running`|`skipped`; does not call `queue_retry`; does not mutate job status/renglones/acta.
- `compras-oc-match-pipeline`: extract-only refresh path (`extract_one` → clear stamp → FOR UPDATE → `apply_writeback` → restamp if routeable); never rematch/Excel; never write `numero_factura`; no alerts; do not persist extract JSON.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/components/compras/_shared/DataTable.jsx` + CSS | Modified | Optional `expandedRowId` / `renderExpandedRow`; default off |
| `frontend/src/components/compras/TabOcMatch.jsx` + CSS + test | Modified | Move `detailBody` into expand slot; toggle; dedicated button + banner |
| `frontend/src/hooks/useOcMatch.js` (or equivalent) | Modified | `refreshDocRefs(id)` POST; no poll-as-running |
| `backend/app/routers/administracion_compras.py` | Modified | New refresh-doc-refs route |
| `backend/app/services/oc_match/` (worker/doc_refs/enqueue helpers) | Modified | Background extract-only persist; reuse `apply_writeback` |
| `backend` focused tests + `TabOcMatch.test.jsx` | Modified | 409 matrix; expand-under-row; button visibility; no rematch |

Unchanged: `gemini_pool.py`; `queue_retry` contract; Retry checkbox path; `numero_factura`; alertas; status CHECK; extract JSON column.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Shared DataTable blast radius | Med | Props default off; no default markup/class change; expand CSS scoped; nested renglones must not inherit hover/click |
| Gemini cost + 503 backoff minutes | Med | Dedicated action only; HTTP returns immediately; no blocking spinner; do not persist JSON |
| Clear stamp at enqueue, then extract fails | Med | Clear stamp **after** successful extract, immediately before write-back. Failed Gemini → stamp unchanged |
| Concurrent Retry while refresh in flight | Med | `append_unique` is idempotent; persist no-ops if job left `done`/`error` |
| TC-error job refresh looks like a rematch | Low | Job stays `error`; no Excel auto-retry; button is dedicated, not Reintentar |
| Ops-ux spec conflict (“below the list”) | Med | Specs MUST MODIFY that scenario; keep “not aside/modal” |
| Line budget 250–450 | Low | No JSON column, no stamp-on-detalle, no Celery |

## Rollback Plan

Revert the DataTable expand slot (other tabs never opted in). Restore TabOcMatch sibling `detailBody` below the list. Remove the refresh-doc-refs route, hook, button, and background extract-only persist. Retry + checkbox, stamp column, `apply_writeback`, and `numero_factura` stay. No Alembic in this change.

## Dependencies

- Parent `feat-compras-oc-match-doc-refs-retry-guard` (write-once stamp + Retry checkbox) must be on `upstream/main` (or stacked only if still open — delivery lock is base `upstream/main`).
- Sibling `feat-compras-oc-match-ops-ux` “below the list” is the UI contract this change amends.
- No new Gemini keys; no new Alembic.

## Success Criteria

- [ ] Selecting job N expands detail immediately under that row at full width; other rows remain visible; pagination is not between the row and its detail; same-row click collapses; no aside/modal.
- [ ] Other `DataTable` consumers are unchanged when expand props are omitted.
- [ ] Dedicated button **Actualizar Factura/s y Pedido/s** appears on detail for `done`|`error` + `gestionar`; hidden for view-only and for `queued`|`running`|`skipped`.
- [ ] `POST …/refresh-doc-refs` returns immediately; 409 unless `done`|`error`; does not call `queue_retry`; does not rematch; does not regenerate Excel; does not mutate status/renglones/acta.
- [ ] Successful extract clears stamp then `apply_writeback` then restamps if routeable; failed extract leaves stamp/job/pedido unchanged; never writes `numero_factura`; no alerts.
- [ ] Error Retry + checkbox `refrescar_doc_refs` still does full rematch; empty retry POST unchanged.
- [ ] `doc_refs_aplicado_at` is not exposed on detalle in this PR.
- [ ] Single PR to `main` from `feat/compras-oc-match-inline-expand-doc-refresh` based on `upstream/main`.
