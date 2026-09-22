# Proposal: feat-compras-oc-match-doc-refs-retry-guard

## Intent

PR #1314 writes OC-match tokens onto Factura/s · Pedido/s. Follow-ups: (A) cap operator input at 500 chars; (B) retry must not re-append tokens the operator deleted unless they opt in.

## Scope

### In Scope
- Pydantic `max_length=500` on Base / Update / Correccion; FE `maxLength={500}`; Text columns unchanged
- `OcMatchJob.doc_refs_aplicado_at` DateTime TZ NULL; Alembic `compras_043` off `compras_042`
- Stamp after routeable write-back; skip write-back when stamp set
- `OcMatchRetryRequest.refrescar_doc_refs: bool = False`; `queue_retry` clears stamp only when True
- TabOcMatch checkbox when Reintentar shown, default OFF, locked Spanish label
- Branch from `origin/feat/compras-oc-match-pedido-doc-refs`; rebase to main after #1314; single PR to `main`

### Out of Scope
- Per-job token snapshot (option 2); wiping fields; touching `numero_factura`
- Changing `append_unique` or `process_oc_match_job(job_id)`
- Exposing stamp on list DTO; capping worker Text at 500

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-oc-match-pipeline`: write-once persist; stamp after routeable write-back
- `compras-oc-match-jobs`: retry body `refrescar_doc_refs`; clear stamp only when True
- `pedidos-compra`: `max_length=500` + FE `maxLength`
- `compras-oc-match-ui`: retry checkbox to opt back into write-back

## Approach

Exploration A1 + B timestamp. First routeable persist writes then stamps. Default retry keeps stamp (renglones/Excel only). Checkbox ON clears stamp → `append_unique` again. Empty POST stays False via `Body(default_factory=...)`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/oc_match_job.py` | Modified | `doc_refs_aplicado_at` |
| `backend/alembic/versions/compras_043_…` | New | Hang off `compras_042` |
| `backend/app/schemas/pedido_compra.py` | Modified | `max_length=500` |
| `backend/app/schemas/oc_match.py` | Modified | `OcMatchRetryRequest` |
| `backend/app/services/oc_match/{enqueue,worker,doc_refs}.py` | Modified | Clear / skip / stamp |
| `backend/app/routers/administracion_compras.py` | Modified | Retry body |
| TabOcMatch + `useOcMatch` + two modals | Modified | Checkbox + `maxLength` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Empty POST 422 | Med | `Body(default_factory=OcMatchRetryRequest)` or Query fallback |
| Stamp on no-op tipo | Med | Stamp only after routeable write |
| Worker Text >500 then GET 500 | Low | Do not cap `append_unique` |
| Apply on ean-extract worktree | High | Stack on #1314 branch only |

## Rollback Plan

Downgrade `compras_043` (drop stamp). Revert retry body, persist guard, checkbox, `max_length`. Text columns and `numero_factura` stay.

## Dependencies

- Parent PR #1314. Stack until merge; then rebase `upstream/main`.

## Success Criteria

- [ ] First routeable persist writes + stamps; default retry does not rewrite tokens
- [ ] Checkbox ON appends again without wipe
- [ ] Empty POST still retries; `process_oc_match_job(job_id)` unchanged
- [ ] Operator PUT >500 → 422; FE `maxLength=500`; no silent slice
