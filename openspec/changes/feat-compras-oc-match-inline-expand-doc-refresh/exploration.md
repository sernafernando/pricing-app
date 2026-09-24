# Exploration: feat-compras-oc-match-inline-expand-doc-refresh

Post-live follow-up to `feat-compras-oc-match-ops-ux` (expand-below-list) and `feat-compras-oc-match-doc-refs-retry-guard` (write-once stamp + error Retry checkbox). Gabe locked two operator asks in one change:

1. **Inline accordion.** Selecting a job expands detail **under that row**, not after the entire list.
2. **Dedicated Factura/s + Pedido/s refresh** that re-extracts (Gemini) and `apply_writeback` without rematch/Excel. Error-job **Reintentar** + checkbox `refrescar_doc_refs` stays.

Honor locks in `state.yaml`. This exploration does not invent product locks Gabe did not give.

---

## Current vs desired expand UX

### Current (ops-ux lock `detail_ux: expand_below_full_width`)

`TabOcMatch` is a single-column stack:

1. Filters + job `DataTable` (`onRowClick` → `setSelectedId`).
2. Pagination under the table.
3. **Then** `{selected && <div className={styles.detailBody}>…}` — a card **after the whole list**.

Evidence:

- `frontend/src/components/compras/TabOcMatch.jsx` lines 253–423: `.layout` column; list pane first; detail sibling after it.
- `TabOcMatch.module.css` `.layout { flex-direction: column }`.
- Test lock: `expands detail below the list, not as aside or modal` (`TabOcMatch.test.jsx`).
- Parent UI spec: “Selecting a job MUST expand its detail below the list at full interface width.”

That was the right rejection of the old **side pane** (24–28rem clipped renglones). Operators still lose the selected row: with 50 jobs they must scroll past the table (and pagination) to see renglones/acta/actions.

Selection is already single-job (`selectedId` in `useOcMatch`). Detail loads via `GET /oc-match/jobs/{id}`. No modal, no `<aside>`.

### Desired (this change lock `expand_ux: accordion_under_selected_row`)

Click job **N** → detail (meta, actions, renglones, acta) renders **immediately under row N**, still full width, still not a side pane or modal. Other rows stay visible above and below. Pagination stays after the table, not between the selected row and its detail.

This **MODIFIES** the ops-ux UI requirement “below the list” → “under the selected row”. Keep: no aside, no modal, full-width renglones, CF tokens, `administracion.ver_ordenes_compra` to view.

---

## Options for inline row expand

Shared `DataTable` (`frontend/src/components/compras/_shared/DataTable.jsx`) is the blocker:

- One `<tr>` per row. No `renderExpanded`, no `colSpan` slot, no fragment API.
- Used by TabPedidosCompra, TabOrdenesPago, TabReconciliacion, TabOcMatch (list + renglones), and others.
- `table-layout: fixed`, clickable rows, no dedicated test file.
- Cannot inject a sibling row from outside `<tbody>`.

### Option E1 — Extend DataTable with an optional expand slot (recommended)

Additive props, default off (other tabs unchanged):

```js
expandedRowId,          // id | null
renderExpandedRow,      // (row) => ReactNode
```

After the matching `<tr>`, insert:

```jsx
<tr className={styles.expandedRow} onClick={stopPropagation}>
  <td colSpan={columns.length}>{renderExpandedRow(row)}</td>
</tr>
```

- **Pros:** Column alignment stays; pagination stays outside; TabOcMatch reuses existing `detailBody`; ~30–50 lines + CSS (disable hover accent on the expand `<tr>`). Matches TrazaViewer / TabEnviosFlex fragment-row pattern without copying a whole table.
- **Cons:** Shared-component blast radius; must not change default markup/classes for other tabs; nested renglones `DataTable` inside the expand cell (already `tables[1]` in tests — still true).
- **Effort:** Low–Medium.

### Option E2 — TabOcMatch-only custom `<table>`

Fork DataTable markup in TabOcMatch (colgroup, clickable rows, expand `<tr>`).

- **Pros:** Zero shared risk.
- **Cons:** Duplicates column/hover/empty patterns; drift vs compras table; more CSS. Against the decision ladder (reuse first).
- **Effort:** Medium.

### Option E3 — CSS-only / keep sibling card, fake “under row”

Cannot place a sibling `div` visually between `<tr>`s without breaking `table-layout` or using absolute positioning. Rejected.

### Option E4 — Replace list with a non-table accordion list

Loses aligned Job / Pedido / Estado columns. Rejected.

**Recommend E1.** Propose can lock. Click-same-row: recommend **toggle collapse** (standard accordion); click another row moves the expand. Not a Gabe lock — propose may lock.

---

## Current doc-refs + retry path

| Layer | Today |
|---|---|
| `OcMatchJob` | No extract JSON column. Stamp `doc_refs_aplicado_at` only. |
| Worker | `extract_one` (Gemini) → match → excel → `_persist`. Extract lives in memory. |
| Persist write-back | After fence + renglones: if `extracted` and stamp is NULL → `PedidoCompra` `SELECT FOR UPDATE` → `apply_writeback` → stamp if routeable. **Never writes `numero_factura`.** No alertas. |
| Excel-error | `RechazoExcel` (incl. “USD sin tipo de cambio”) still passes `extracted`. Parent lock: write-back **does** run. TC-error jobs can already have Factura/s + Pedido/s. |
| `POST …/retry` | `gestionar_ordenes_compra`. 409 unless `error` (after reclaim). `queue_retry` → `queued`, clears phase/error, **optionally** clears stamp. Then **full** `process_oc_match_job` (rematch + Excel). |
| FE | Checkbox + Reintentar **only** when `showRetry` (error + gestionar). Done jobs: Excel only. No dedicated refresh. |

`apply_writeback` is append-only unique (casefold, `"; "`). `comprobante_pago` / `otro` / empty → no-op, no stamp.

Locked: dedicated action; label hint **Actualizar Factura/s y Pedido/s**; `available_on: [done, error]`; must not rematch; must not regenerate Excel; clears stamp; **must re-extract** (JSON not persisted); keep error Retry checkbox; permission `administracion.gestionar_ordenes_compra`; no `numero_factura`; no alerts from doc-refs.

---

## Options for dedicated doc-refs refresh API

### Option A1 — New endpoint (recommended)

```
POST /administracion/compras/oc-match/jobs/{job_id}/refresh-doc-refs
```

- Permiso: `require_permiso("administracion.gestionar_ordenes_compra")` (same as retry).
- Empty body. Response: existing `OcMatchJobResponse` (or 202 + same DTO).
- **409** if status is not `done` or `error` (after reclaim, same 404 helper as today).
- Does **not** call `queue_retry`. Does **not** change `status`, renglones, `excel_rel_path`, acta.
- Background entry (see execution below): load adjunto bytes → `extract_one` (no Session) → short persist session: set `doc_refs_aplicado_at = None`, `FOR UPDATE` pedido, `apply_writeback`, re-stamp if True.
- Reuse `doc_refs.apply_writeback` unchanged.

- **Pros:** Matches “dedicated action”; retry contract stays error-only + full rematch; no accidental `queued` flip on a done job; checkbox path untouched.
- **Cons:** One more route + hook method + tests.
- **Effort:** Low–Medium.

### Option A2 — Reuse `POST …/retry` with `mode` / `solo_doc_refs`

e.g. `{ mode: "doc_refs_only" }` or `{ refrescar_doc_refs: true }` on **done**.

- **Pros:** One URL.
- **Cons:** `queue_retry` **requires error** and sets `queued`. Done refresh would have to bypass that — two behaviors on one verb. Easy to rematch by mistake. Conflicts with “dedicated action” + “must not rematch”. Empty POST must stay “full retry, no stamp clear”.
- **Effort:** Medium — **rejected**.

### Option A3 — Persist extract JSON now, refresh without Gemini

- **Pros:** Cheap refresh.
- **Cons:** Gabe locked extract required because JSON is **not** on the job. New JSON column is a different change (PII, Alembic, stale extract). Out of scope.
- **Rejected.**

**Recommend A1.** Propose can lock path + 409 matrix from Gabe’s `available_on`.

---

## Status eligibility

| Status | Dedicated refresh? | Why |
|---|---|---|
| `done` | **Yes** (locked) | Numbers may be missing/stale; operator must not rematch. |
| `error` | **Yes** (locked) | Includes TC/`RechazoExcel` jobs that already wrote tokens. Refresh updates numbers; job **stays** `error`. Full rematch remains Retry + optional checkbox. |
| `queued` | **No** (recommend) | Worker about to extract; concurrent Gemini + stamp race. |
| `running` | **No** (recommend) | Same race with `_persist` write-back. |
| `skipped` | **No** (recommend) | MIME not Gemini-eligible (`SKIP_MESSAGE`). `extract_one` would fail. |

Gabe locked `available_on: [done, error]`. Treat as **exclusive**. Propose can lock 409 for queued/running/skipped without a new Gabe ask.

View-only users (`ver_ordenes_compra`): hide the dedicated button (same as Retry). Backend still 403 without gestionar.

---

## Execution: sync HTTP vs BackgroundTasks

`extract_one` uses `GeminiPool.generate_json`. 503 backoff can idle **minutes**. The worker exists because Gemini must not hold a request `Session`.

| Option | Tradeoff |
|---|---|
| **B1. BackgroundTasks two-session** (recommended) | Mirror worker: claim adjunto in a short session, close, extract, persist write-back in a new session. HTTP returns 202/200 immediately. Job status stays `done`/`error`. |
| B2. Sync in the request | Simpler FE busy-on-POST. Risks proxy timeout and pinned `get_db` if not `get_current_user_transient`. |
| B3. Flip job to `queued`/`running` | Looks like rematch; poll would show Procesando; **violates** must-not-rematch UX. |

**Recommend B1.** FE: `useOcMatch.refreshDocRefs(id)` → POST → inline banner “Actualización encolada” / error `detail`. Optional later: expose `doc_refs_aplicado_at` on **detalle** so stamp movement is visible. Not required for v1 (numbers live on PedidoCompra, not TabOcMatch). Propose can lock B1; ask Gabe only if they need a spinner until Gemini finishes.

Do **not** reuse `progress_phase` (`extracting|matching|excel`) — that means a full running job.

Concurrency: if the operator Reintenta while a refresh task is in flight, `append_unique` is idempotent. Refresh persist should no-op if the job left `done`/`error` (retry already claimed). Lost-claim style: skip write-back if status is not `done` or `error` at persist time.

---

## Risks

1. **Gemini cost.** Every dedicated refresh is one `extract_one` (not a second `match_renglones`). Still money + 503 backoff. Do not persist JSON in this change (locked).
2. **Write-once stamp.** Refresh **must** clear `doc_refs_aplicado_at` or persist will skip. Clear at persist-after-extract (not at HTTP accept) so a crashed extract does not leave a naked NULL that a later full retry (checkbox off) would then rewrite… Wait: if we clear only after a successful extract, a failed extract leaves the old stamp — correct. If we clear at enqueue, a failed refresh + later default Retry would skip write-back (stamp already null… actually default retry **keeps** stamp; if we nulled at enqueue and extract failed, stamp stays null and the next **full** persist would write — usually desirable). **Recommend: clear stamp in the refresh persist session immediately before `apply_writeback`, only after extract succeeds.** Failed Gemini → stamp unchanged, job unchanged.
3. **TC-error jobs can still refresh numbers.** Intended. First persist may already have written tokens; refresh re-extracts and `append_unique` (no wipe). Job stays `error`. Do not auto-retry Excel.
4. **Shared DataTable.** Expand CSS (`tr:hover` on the colspan row) must be scoped so nested renglones table does not inherit list-row click/hover accent.
5. **Ops-ux spec conflict.** Apply must MODIFY “below the list” scenarios; keep “not aside/modal”.
6. **No alerts.** Refresh must not call alertas/notificaciones (parent already silent).
7. **Line budget.** Forecast 250–450. DataTable slot + new route + hook + tests fits one PR if we do not persist extract JSON or add a refresh-status column.

---

## Recommended approach

One cohesive change, single PR to `main` (locked):

| Item | Recommendation | Who locks |
|---|---|---|
| Expand | DataTable optional `expandedRowId` + `renderExpandedRow`; TabOcMatch moves `detailBody` into that slot | Propose |
| Same-row click | Toggle collapse | Propose |
| Dedicated API | `POST …/oc-match/jobs/{id}/refresh-doc-refs` | Propose (Gabe: dedicated action) |
| Eligibility | `done` + `error` only; 409 otherwise | Propose (Gabe: `available_on`) |
| Pipeline | BackgroundTasks; extract-only; clear stamp then `apply_writeback`; no rematch/Excel/status change | Propose |
| Retry checkbox | Unchanged; error jobs only | Gabe locked |
| Permiso / `numero_factura` / alerts | Unchanged | Gabe locked |
| Extract JSON column | Do not add | Gabe locked |

**Out of scope:** persist extract JSON; Celery; Gemini backoff retune; wiping Factura/s·Pedido/s; writing `numero_factura`; alerts; changing MIME/enqueue; widening status CHECK.

**Spec impact:** MODIFY `compras-oc-match-ui` (expand under row; dedicated button + keep checkbox). ADD/MODIFY `compras-oc-match-jobs` (new route, 409). ADD/MODIFY `compras-oc-match-pipeline` (extract-only refresh path, stamp clear).

---

## Open questions for propose

**Propose can lock (do not block on Gabe):**

1. API path `POST /administracion/compras/oc-match/jobs/{job_id}/refresh-doc-refs` vs retry mode — **new path**.
2. queued / running / skipped — **no refresh, 409**.
3. DataTable expand slot vs TabOcMatch-only table — **shared slot**.
4. Execution — **BackgroundTasks two-session**; do not flip status.
5. Stamp clear — **after successful extract, immediately before write-back**.
6. Same-row click — **toggle**.

**Ask Gabe only if they reject a recommend:**

1. Need a blocking spinner until Gemini finishes? (Default: no; banner “en cola”.)
2. Expose `doc_refs_aplicado_at` on detalle in this PR? (Default: no; numbers are on the pedido.)

---

## Ready for proposal

**Yes.** Product locks are sufficient. Pending API/eligibility items are narrowed to recommendations propose can adopt.
