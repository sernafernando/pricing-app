# Design: feat-compras-oc-match-doc-refs-retry-guard

## Technical Approach

#1314 follow-up: (A) Pydantic/HTML 500; Text stays. (B) write-once via `doc_refs_aplicado_at`; checkbox opts back into `append_unique`. Deltas: pipeline, jobs, pedidos-compra, ui. Pydantic v2 + `datetime.now(UTC)`. FE: copy `.checkboxLabel`; no forms-tesla checkbox.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| max_length | Base/Update/Correccion vs input-only vs `String(500)` | Gabe lock vs GET 500 if worker Text >500 vs ALTER | `Field(None, max_length=500)` on Base/Update/Correccion; Text unchanged |
| Already-applied | DateTime stamp vs bool vs extra one-shot vs kwarg on worker | Audit “when”; survive `BackgroundTasks`; no signature change | `doc_refs_aplicado_at` TZ NULL; `queue_retry` clears only when True |
| API | Body vs Query | Empty POST must keep working | `OcMatchRetryRequest` + `Body(default_factory=OcMatchRetryRequest)` (same router already uses `default_factory=dict`). Fallback: `Query(False)` |
| Stamp when | After any persist vs after routeable write vs after mutate | No-op tipo would block a better retry | After `apply_writeback` returns True (routeable + ≥1 token), even if append is a no-op |
| Worker entry | `process_oc_match_job(job_id, refrescar=…)` vs row stamp | Future `add_task(job.id)` would drop the flag | Keep `job_id` only |
| FE | Checkbox vs confirm modal | Gabe asked checkbox | Next to Reintentar when `showRetry`; default off |

## Data Flow

```
first persist (stamp NULL)
  fence → renglones → if extracted and stamp is None
    → SELECT Pedido FOR UPDATE → apply_writeback → if True: stamp now(UTC)

default retry (checkbox OFF)
  POST {} → queue_retry(refrescar=False) → stamp stays
  → persist skips write-back; renglones/Excel/acta still run

refresh retry (checkbox ON)
  POST {refrescar_doc_refs:true} → stamp = NULL
  → persist append_unique again (no wipe) → re-stamp
```

```
if extracted is None: return          # no stamp
if job.doc_refs_aplicado_at: return   # skip write-back
locked = PedidoCompra FOR UPDATE
if apply_writeback(locked, extracted):
    job.doc_refs_aplicado_at = datetime.now(UTC)
```

Lost fence (`rowcount==0`) returns before this. `comprobante_pago`/`otro`/empty → False → no stamp.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/models/oc_match_job.py` | Modify | `doc_refs_aplicado_at` DateTime TZ NULL after `finished_at`. No index. |
| `backend/alembic/versions/compras_043_oc_match_doc_refs_aplicado.py` | Create | Column on `compras_oc_match_jobs`; `down_revision = compras_042_pedido_doc_refs`. Rehang if tip moved. |
| `backend/app/schemas/pedido_compra.py` | Modify | Both fields `Field(None, max_length=500)` on Base/Update/Correccion. |
| `backend/app/schemas/oc_match.py` | Modify | `OcMatchRetryRequest`; no stamp on `OcMatchJobResponse`. |
| `backend/app/services/oc_match/doc_refs.py` | Modify | `apply_writeback(...) -> bool`. True iff routeable + ≥1 token. |
| `backend/app/services/oc_match/enqueue.py` | Modify | `queue_retry(..., refrescar_doc_refs=False)`; clear stamp only if True. |
| `backend/app/services/oc_match/worker.py` | Modify | Skip when stamp set; stamp after True. |
| `backend/app/routers/administracion_compras.py` | Modify | `Body(default_factory=OcMatchRetryRequest)`; pass flag. |
| `backend/tests/unit/test_oc_match_reclaim.py` | Modify | Default keeps stamp; True clears. |
| `backend/tests/unit/test_oc_match_doc_refs.py` | Modify | Bool True/False by tipo. |
| `backend/tests/integration/test_oc_match_worker.py` | Modify | Write-once; refresh append; skip-tipo; fence. |
| `backend/tests/integration/test_oc_match_enqueue.py` | Modify | Empty POST; body true. |
| schema / pedidos unit | Modify | PUT >500 → 422. |
| `frontend/src/hooks/useOcMatch.js` | Modify | `retry(id, { refrescar_doc_refs })` JSON. |
| `frontend/src/components/compras/TabOcMatch.jsx` | Modify | Checkbox; reset on `selected.id`. |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modify | Copy `.checkboxLabel` from `ModalPedidoCompra.module.css`. |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modify | Checkbox gate + payload. |
| `ModalPedidoCompra.jsx` / `ModalCorregirPedido.jsx` | Modify | `maxLength={500}` on both inputs. |

Unchanged: `append_unique`, `numero_factura`, `editar_pedido`, MIME enqueue, acta, Excel, `CAMPOS_EDITABLES_*`, `ModalPedidoDetalle`, list DTO stamp.

## Interfaces / Contracts

```python
class OcMatchRetryRequest(BaseModel):
    refrescar_doc_refs: bool = False
```

```js
retry(id, { refrescar_doc_refs = false } = {})
api.post(`${OC_MATCH_BASE}/${id}/retry`, { refrescar_doc_refs })
```

FE label exactly: `También actualizar Factura/s y Pedido/s`. Reset `useState(false)` when `selected?.id` changes. Place inside `.actions` next to Reintentar.

Worker Text may exceed 500; operator PUT then 422s; GET detalle may 500-validate if Response inherits Base. Do not slice `append_unique` this change.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `queue_retry` default vs refresh; `apply_writeback` bool; schema 422 | reclaim + doc_refs + pedido schema |
| Integration | empty POST; body true; write-once; refresh append; no stamp on skip tipo | enqueue + worker |
| FE | checkbox only with Reintentar; default off; label; `retry` args | extend `TabOcMatch.test.jsx` |
| E2E | N/A | no modal test file; `maxLength` is HTML |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

`compras_043` adds nullable TZ DateTime (existing jobs NULL → first persist still writes). Downgrade drops it. Branch from `origin/feat/compras-oc-match-pedido-doc-refs`; rebase `upstream/main` after #1314. Single PR to `main`. Not based on ean-extract-fallback (TabOcMatch EAN vs `.actions` hunks).

## Open Questions

None. Locks are in `state.yaml`.
