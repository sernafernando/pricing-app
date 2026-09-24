# Proposal: fix-compras-oc-match-refresh-normalized-factura

## Intent

PR #1343 refresh writes `facturas_documento` text only. Pedidos list **Factura** chip / `tiene_numero_factura` / alerts read `pedido_factura_documentos`. A deleted-then-refreshed number can reappear (re-extract wins). Chicho RED + Gabe YELLOW: mirror worker persist; warn; no tombstone.

## Scope

### In Scope

- After `apply_writeback` True in `refresh_doc_refs._persist_writeback`, if `normalize_tipo(...)=="factura"` and `token_or_none(nro_documento)`, call `pedidos_service.persist_factura_documento(db, pedido=..., numero=..., created_by_id=int(pedido.creado_por_id))` then `flush`. Same FOR UPDATE session as worker.
- UI warning (button `title` and helper near **Actualizar Factura/s y Pedido/s**): re-reads PDF; may restore manually deleted numbers.
- Unit test that does **not** mock `apply_writeback` for factura → `pedido_factura_documentos` (or integration asserting the row). Keep extract-fail / skip tests.
- Push the same branch / PR #1343.

### Out of Scope

- Tombstone deleted tokens; automatic re-extract; expand / DataTable UX; jobs HTTP contract; worker refactor; `numero_factura`; alerts; extract JSON; Alembic.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `compras-oc-match-pipeline`: refresh persist MUST also insert the normalized factura row (worker parity).
- `compras-oc-match-ui`: dedicated refresh MUST warn that re-extract may restore deleted numbers.

No `compras-oc-match-jobs` delta (endpoint unchanged).

## Approach

Copy worker’s post-writeback block into `_persist_writeback`. Do not extract a shared helper. Re-extract still append-unique; `apply_writeback` True even on no-op append so a deleted row is re-inserted. FE-only copy; expand stays.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/oc_match/refresh_doc_refs.py` | Modified | Persist factura row + flush after True |
| `backend/tests/unit/test_oc_match_refresh_doc_refs.py` | Modified | Real `apply_writeback` path; keep fail/skip |
| `frontend/src/components/compras/TabOcMatch.jsx` + CSS + test | Modified | `title` + helper; expand untouched |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Mocked writeback hides missing persist | High | New test uses real `apply_writeback` |
| Restore surprises operators | Med | Locked warning copy; no tombstone |
| Shared helper drift | Low | Mirror worker in place; do not refactor |

## Rollback Plan

Revert the persist block and FE warning. Parent refresh route, expand, stamp, `apply_writeback`, worker persist stay. No Alembic.

## Dependencies

- Parent `feat-compras-oc-match-inline-expand-doc-refresh` on PR #1343.
- `persist_factura_documento` already constancia-only (no notify).

## Success Criteria

- [ ] Factura refresh inserts `pedido_factura_documentos` with `created_by_id=pedido.creado_por_id` in the same session.
- [ ] Non-factura / empty `nro_documento` / `apply_writeback` False does not persist a row.
- [ ] Extract fail and status-left skip still leave stamp/job/pedido unchanged.
- [ ] Dedicated button shows restore warning; expand UX unchanged.
- [ ] Same PR #1343.
