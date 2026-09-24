# Design: fix-compras-oc-match-refresh-normalized-factura

## Technical Approach

Chicho RED: `_persist_writeback` stops at `apply_writeback` + restamp. Worker also writes `pedido_factura_documentos`. Copy that block in place. Gabe YELLOW: re-extract wins; warn on the existing button; no tombstone. Jobs HTTP and expand stay.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| Persist site | Mirror worker vs shared helper | Drift vs extra refactor | **Copy worker block in `_persist_writeback`** |
| Session | Same FOR UPDATE vs new | Chip/alert must see the row | **Same `db`; then `flush`** |
| `created_by_id` | `pedido.creado_por_id` vs current user | Refresh is background | **`int(pedido.creado_por_id)`** |
| Deleted numbers | Tombstone vs re-extract wins | Product lock | **Re-extract wins; warn** |
| Warning | `title` only vs helper only | and/or lock | **Both** |
| Test | Mock writeback vs real | Mock hid the bug | **Do not mock `apply_writeback`** |

## Data Flow

```
_persist_writeback (unchanged fence)
  job FOR UPDATE; skip if not done|error
  clear stamp; pedido FOR UPDATE
  if apply_writeback(pedido, extracted):          # real fn
      restamp datetime.now(UTC)
      nro = token_or_none(extracted["nro_documento"])
      if normalize_tipo(tipo) == "factura" and nro:
          persist_factura_documento(db, pedido=pedido,
              numero=nro, created_by_id=int(pedido.creado_por_id))
      db.flush()
```

`apply_writeback` is True for routeable + ≥1 token even when append is a no-op → deleted row comes back. False → no persist, no restamp.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/oc_match/refresh_doc_refs.py` | Modify | Import `normalize_tipo`, `token_or_none`, `pedidos_service`; after True, persist + flush |
| `backend/tests/unit/test_oc_match_refresh_doc_refs.py` | Modify | Real writeback → row/call; keep fail/skip |
| `frontend/src/components/compras/TabOcMatch.jsx` | Modify | `title` + helper; do not touch expand |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modify | `.refreshHint` CF tokens |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modify | Assert `title` + helper |

Unchanged: `worker.py`, `doc_refs.py`, `pedidos_service.py`, router, DataTable, `useOcMatch`, jobs contract.

## Interfaces / Contracts

```python
# worker.py lines 242–252 — copy exactly
if apply_writeback(locked, extracted):
    job.doc_refs_aplicado_at = datetime.now(UTC)
    nro_documento = token_or_none(extracted.get("nro_documento"))
    if normalize_tipo(extracted.get("tipo_documento")) == "factura" and nro_documento is not None:
        pedidos_service.persist_factura_documento(
            db, pedido=locked, numero=nro_documento,
            created_by_id=int(locked.creado_por_id),
        )
    db.flush()
```

Locked FE copy (es-AR, next to the existing label):

- `title`: `Relee el PDF. Puede restaurar números borrados a mano.`
- helper: `Vuelve a leer el PDF y puede restaurar números de factura o pedido que se hayan borrado a mano.`

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Factura True → persist called / row; no-op append still persists; non-factura / empty / False skip | `test_oc_match_refresh_doc_refs.py` — **do not mock `apply_writeback`** on that path. Spy `persist_factura_documento` or assert row. Pedido needs `creado_por_id`. |
| Unit | Extract fail keeps stamp; status-left skip | Keep existing tests |
| Vitest | `title` + helper when button shown; hidden view-only | `TabOcMatch.test.jsx` |
| E2E | N/A | No Gemini in browser |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR, executable-file, or process-integration boundary.

## Migration / Rollout

No migration. Same branch `feat/compras-oc-match-inline-expand-doc-refresh`, same PR #1343 → `main`.

**Rollback:** drop persist block + FE warning. Parent refresh/expand stay.

## Open Questions

None. Locks in `state.yaml`.
