# Exploration: feat-compras-oc-match-doc-refs-retry-guard

Gabe + Chicho follow-ups on PR **#1314** (`feat/compras-oc-match-pedido-doc-refs`, still **OPEN**, MERGEABLE, CI green, targets `main`). Two small locks in one change:

**A.** `max_length=500` on `facturas_documento` / `pedidos_documento` Pydantic input schemas. Column stays `Text`.

**B.** Write-once OC-match write-back. Retry stays renglones/Excel-only unless the operator checks **También actualizar Factura/s y Pedido/s**.

New branch `feat/compras-oc-match-doc-refs-retry-guard` stacked on `origin/feat/compras-oc-match-pedido-doc-refs` until #1314 merges, then `upstream/main`. Current workspace tip `feat/compras-oc-match-ean-extract-fallback` is **not** the base (no `doc_refs.py`, no pedido Text columns, no `compras_042`).

Out of scope: per-job token snapshot (option 2), wiping fields, touching `numero_factura`.

---

## Exploration: Doc-ref max_length + retry write-once guard

### Current State

**#1314 write-back (read from `origin/feat/compras-oc-match-pedido-doc-refs`).** `pedidos_compra.facturas_documento` / `pedidos_documento` are **nullable `Text`** (`compras_042_pedido_doc_refs`, revises `compras_041`). Not `String(n)` — no DB length to migrate for part A.

Pydantic on that branch (parent lock `pydantic_max_length: none`):

| Schema | Fields | Constraint |
|---|---|---|
| `PedidoCompraBase` (Create + Response inherit) | both | `str \| None = None` |
| `PedidoCompraUpdate` | both | same |
| `CorreccionPedidoRequest` | both | same |

`numero_factura` is already `Field(None, max_length=50)` on the same models. Worker `append_unique` is **not** Pydantic — it can grow the Text past 500.

**Persist path** (`worker._persist` after claim fence + `_replace_renglones`):

```
if extracted is None: return
SELECT PedidoCompra FOR UPDATE
apply_writeback(locked, extracted)
```

`extracted` is passed even when `error` is set (`RechazoExcel` after a good extract). Parent lock `writeback_on_excel_error_if_extract_ok: true` — first persist **does** write on excel-error. That is the operator bug: job ends `error`, tokens land, operator deletes them, **Reintentar** re-extracts the same numbers, `append_unique` puts them back.

`apply_writeback` is append-only unique (casefold, first-seen casing, `"; "` join). Never writes `numero_factura`. `comprobante_pago` / `otro` / unknown → no-op.

**Retry today.** One job per `(pedido_id, attachment_id)` — retry **reuses** the row.

| Layer | Behavior |
|---|---|
| `POST /oc-match/jobs/{job_id}/retry` | No body, no query. Permiso `administracion.gestionar_ordenes_compra`. 409 if not `error` (after reclaim). |
| `queue_retry` | `error` → `queued`; clears `error_message`, `progress_phase`, `started_at`, `finished_at`. No write-back flag. |
| `BackgroundTasks.add_task(process_oc_match_job, job.id)` | Single arg. Enqueue wrapper and worker both `process_oc_match_job(job_id: int)`. |
| First upload enqueue | Same `process_oc_match_job(job.id)` — must keep writing on first persist (`aplicado_at` NULL). |

`OcMatchJob` has timestamps (`started_at`, `finished_at`, …) and **no** JSON/options column. `OcMatchJobResponse` has no retry payload fields.

**FE TabOcMatch.** `showRetry = puedeGestionar && (retryable \|\| status === 'error')`. `.actions` holds Descargar Excel + **Reintentar**. `handleRetry` → `retry(selected.id)` with no payload. `useOcMatch.retry` is `api.post(\`${OC_MATCH_BASE}/${id}/retry\`)`. No checkbox on this tab. Checkbox CSS already exists on `ModalPedidoCompra` (`.checkboxLabel` inline-flex, CF tokens). `forms-tesla.css` has **no** checkbox primitive.

**Pedido modals on #1314.** Factura/s · Pedido/s inputs in `ModalPedidoCompra` / `ModalCorregirPedido` (no `maxLength`). Detalle is read-only.

**This workspace.** `feat/compras-oc-match-ean-extract-fallback` — EAN cell only. `doc_refs.py` and the Text columns are **absent** here. Explore read them from `origin/feat/compras-oc-match-pedido-doc-refs`.

### Affected Areas

- `backend/app/models/oc_match_job.py` — add `doc_refs_aplicado_at` DateTime(timezone=True) NULL
- `backend/alembic/versions/compras_043_…` — hang off `compras_042_pedido_doc_refs`; rehang if #1314 merge moves the compras tip
- `backend/app/schemas/pedido_compra.py` — `max_length=500` on Base / Update / Correccion
- `backend/app/schemas/oc_match.py` — `OcMatchRetryRequest { refrescar_doc_refs: bool = False }`
- `backend/app/services/oc_match/enqueue.py` — `queue_retry(..., refrescar_doc_refs: bool = False)`; if True, set `doc_refs_aplicado_at = None`. Do **not** change `process_oc_match_job(job_id)` signature
- `backend/app/services/oc_match/worker.py` — persist: skip `apply_writeback` when stamp is set; stamp after a routeable write-back
- `backend/app/services/oc_match/doc_refs.py` — keep `append_unique`; optional `bool` return if persist needs “did we attempt a routeable write”
- `backend/app/routers/administracion_compras.py` — `reintentar_oc_match_job` accepts the flag; pass into `queue_retry`
- `backend/tests/unit/test_oc_match_reclaim.py` — `queue_retry` default vs refresh
- `backend/tests/unit/test_oc_match_doc_refs.py` / `tests/integration/test_oc_match_worker.py` — write-once + refresh append
- `backend/tests/integration/test_oc_match_enqueue.py` — empty POST still retries; body/query true clears stamp
- `frontend/src/hooks/useOcMatch.js` — `retry(id, { refrescar_doc_refs })`
- `frontend/src/components/compras/TabOcMatch.jsx` + `.module.css` + `.test.jsx` — checkbox next to Reintentar
- `frontend/src/components/compras/ModalPedidoCompra.jsx` / `ModalCorregirPedido.jsx` — `maxLength={500}`
- Later deltas: `compras-oc-match-pipeline`, `compras-oc-match-jobs`, `compras-oc-match-ui`, `pedidos-compra`

Unchanged: `append_unique` join/dedupe, `numero_factura`, `editar_pedido`, enqueue MIME, acta, Excel writer, `CAMPOS_EDITABLES_*` (already include the fields on #1314).

### Approaches

#### A. max_length

1. **Pydantic `max_length=500` on Base / Update / Correccion; column stays Text (recommended)**
   - Pros: Matches Gabe; same pattern as `numero_factura` max_length; no Alembic type change; Create inherits Base
   - Cons: `PedidoCompraResponse` inherits Base — GET would 500-validate if worker already stored >500. Unlikely (new columns, #1314 not on main). Worker `append_unique` can still exceed 500; operator PUT then 422s
   - Effort: Low

2. **Input-only max_length (Update + Correccion + override Create; Response unconstrained)**
   - Pros: Long AI-joined Text never breaks GET
   - Cons: Split from Gabe’s “Base/Update/Correccion”; more field duplication
   - Effort: Low

3. **Also `String(500)` + Alembic ALTER**
   - Pros: DB enforces
   - Cons: User/parent said Text stays; ALTER on PostgreSQL Text→Varchar is avoidable risk
   - Effort: Medium — **rejected**

#### B. “Already applied” persistence

1. **`doc_refs_aplicado_at` DateTime TZ NULL; refresh clears it in `queue_retry` (recommended)**
   - First persist with a routeable extract: write, then stamp `datetime.now(UTC)`
   - Retry default OFF: stamp stays → persist skips write-back, still replaces renglones/Excel
   - Retry checkbox ON: `queue_retry` sets stamp `NULL` → persist writes again (`append_unique`, no wipe) → re-stamps
   - Pros: One column; audit “when”; no `process_oc_match_job` signature change; survives BackgroundTasks (intent lives on the row); matches existing job timestamps; crash after clear-before-persist still writes on the next run (intent not yet applied)
   - Cons: Clearing the stamp drops the first-applied instant (re-stamp is “last applied”)
   - Effort: Low

2. **Boolean `doc_refs_aplicado` default false**
   - Pros: Smaller
   - Cons: No when; same handoff needs a second one-shot or clear-on-refresh anyway
   - Effort: Low

3. **Timestamp + one-shot `refrescar_doc_refs` bool consumed in persist**
   - Pros: Keeps first-applied time forever
   - Cons: Two columns for a follow-up Gabe wanted minimal
   - Effort: Low

4. **Pass `refrescar_doc_refs` into `process_oc_match_job(job_id, refrescar=…)` only**
   - Pros: No refresh column
   - Cons: Enqueue wrapper + every `add_task` / test spy must thread the kwarg; a later `process_oc_match_job(job.id)` (tests, future sweeper) silently defaults OFF and cannot honor a checkbox already committed
   - Effort: Medium — worse than stamping on the row

#### B. API shape

1. **`OcMatchRetryRequest` body, `refrescar_doc_refs: bool = False`, `Body(default_factory=…)` (recommended)**
   - Pros: Explicit Pydantic v2 contract; other compras writes use Body; empty POST can keep working if default_factory is used (existing tests POST with no body)
   - Cons: Must confirm FastAPI accepts missing body (if 422, add `Body(None)` or fall back to Query)
   - Effort: Low

2. **Query `?refrescar_doc_refs=false`**
   - Pros: Zero body change; current `api.post(url)` stays valid
   - Cons: Mutation flag on query is easier to miss in reviews
   - Effort: Low — acceptable fallback

#### B. FE placement

1. **Checkbox in `.actions` next to Reintentar, only when `showRetry` (recommended)**
   - Local state default `false`; reset when `selectedId` changes
   - Label exactly: `También actualizar Factura/s y Pedido/s`
   - `.checkboxLabel` copied from `ModalPedidoCompra.module.css` (CF tokens). Do not add a forms-tesla checkbox
   - `retry(id, { refrescar_doc_refs })`; hook sends JSON body (or query if API fallback)
   - Effort: Low

2. **Confirm modal before retry**
   - Cons: Extra chrome; Gabe asked for a checkbox on Reintentar
   - Effort: Medium — **rejected**

### Recommendation

**Part A — approach 1.** `Field(None, max_length=500)` on `facturas_documento` / `pedidos_documento` in `PedidoCompraBase`, `PedidoCompraUpdate`, `CorreccionPedidoRequest`. No Alembic length change (`Text` confirmed). FE: `maxLength={500}` on the two modal inputs (create/edit + corregir). Do **not** silently slice on submit — HTML cap + 422. Detalle stays read-only. Do not cap `append_unique` in this change (call out GET/PUT 422 if a pedido ever accumulates >500 via many PDFs).

**Part B — timestamp + clear-on-refresh.**

| Item | Lock |
|---|---|
| Column | `OcMatchJob.doc_refs_aplicado_at` `DateTime(timezone=True)` NULL. No index. |
| Alembic | `compras_043_oc_match_doc_refs_aplicado` (or next), `down_revision = compras_042_pedido_doc_refs` |
| First persist | If stamp is NULL and extract is routeable (tipo in factura/pedido/proforma/nota_venta and at least one token): `apply_writeback`, then stamp. Excel-error-with-extract still writes + stamps (parent lock). `extracted is None` or no-op tipo: no stamp |
| Retry default OFF | `queue_retry` does not touch the stamp. Persist skips write-back. Renglones/Excel/acta still recalculate |
| Retry checkbox ON | `queue_retry(..., refrescar_doc_refs=True)` sets stamp NULL. Persist appends again. Still no wipe except re-adding extract tokens via `append_unique` |
| API | `OcMatchRetryRequest` body, `refrescar_doc_refs: bool = False`. If empty POST 422s in tests, switch to `Query(False)` — same flag name |
| Worker entry | Keep `process_oc_match_job(job_id: int)` |
| FE | Checkbox only when Reintentar is shown; default off; Spanish label above; `useOcMatch.retry` forwards the flag |
| Response | Do **not** require exposing `doc_refs_aplicado_at` on the list DTO this change (checkbox does not need it) |

**Branch.** Create `feat/compras-oc-match-doc-refs-retry-guard` from `origin/feat/compras-oc-match-pedido-doc-refs` while #1314 is open. After merge, rebase onto `upstream/main` and retarget `main`. Do **not** stack on `feat/compras-oc-match-ean-extract-fallback`. Single PR to `main`.

Sibling note: ean-extract-fallback also edits `TabOcMatch.jsx` (EAN cell). This change edits `.actions` / retry. Different hunks; rebase after either lands.

### Risks

- Empty POST + required Body 422s existing retry tests / `useOcMatch` — use `default_factory` or Query fallback
- Stamping on no-op tipo (`comprobante_pago`) would block a later retry from writing a better classification — **do not stamp** unless the extract was routeable
- Worker can still write Text >500; operator PUT then 422s; if max_length is on Base, GET detalle could 500-validate that row
- Clearing `doc_refs_aplicado_at` on refresh loses first-applied time (acceptable; re-stamp is last applied)
- Lost claim fence (`rowcount == 0`) must not stamp — same as today’s discarded persist
- Multiple PDFs = multiple jobs; guard is **per job**. A second adjunto still writes. Correct
- Apply on the current ean-extract-fallback worktree cannot compile `doc_refs` — implement on the stacked branch only
- `upstream/main` multi-head Alembic: hang off `compras_042`, rehang if the compras tip moved

### Ready for Proposal

Yes — product is locked (Gabe option 3 + max_length 500). Orchestrator should run **propose** next. Implementation waits for design/tasks. No production code in this phase.
