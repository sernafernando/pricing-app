# Proposal: Compras Pipeline Chicho Review Fixes

## Intent

Chicho reviewed PRs #1320–#1324 (Gabe → sernafernando **main**). OC Match writes `facturas_documento`; chips/alerts read `pedido_factura_documentos`. Seed overflows `String(100)`. Factura banners hardcode roles and stack. Fix those plus #1323/#1324 holes. One Novedades draft; Gabe reads before commit.

## Scope

### In Scope
- Shared alta from `apply_writeback` inserts `pedido_factura_documentos` same txn; test chip on
- Optional read-path seed for legacy text-only pedidos
- Amend `compras_044`: truncate/filter to 100, log/skip overflows, UNIQUE/dedupe `(pedido_id, numero)`
- Seed `administracion.ver_alertas_factura` (no default roles); `destinatarios_factura` via `tienePermiso` / resolver
- Banner cap: `max_alertas_visibles` + “+N más”
- Document D-UNDO-R; tests: double undo 409, CC+`pagado_en` → `pagado`, 403
- Empty OC block + “OC no encontrada en ERP”; desvincular-all note (granular if cheap); 1-of-3 test
- `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` — **GATE: no commit until orchestrator shows Gabe the draft**

### Out of Scope
- admin-ocs code; `compras.*` permission codes
- Faltantes recipients (stay `responsable_id`); ERP multi-factura; new PR chain

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-factura-documentos`: writeback+seed → rows; UNIQUE `(pedido_id, numero)`; 100-char seed
- `compras-pipeline-alerts`: recipients = permission holders, not MarcaPM/ADMIN; banner cap
- `pedidos-compra`: chips row-based; optional read-path seed
- `recepcion-estados`: document D-UNDO-R; double-undo / CC+`pagado_en` / 403
- `vincular-oc`: empty ERP-missing block; desvincular-all asymmetry
- `recepcion-deposito`: render empty OC block + Spanish missing copy

## Approach

Shared alta after `apply_writeback` (same FOR UPDATE; casefold-skip dupes). Amend `compras_044` (not on main). Seed permiso like `compras_020`; drop `ROLES_FACTURA` / MarcaPM. Cap banners; “+N más”. Land: **PR1** sync+044, **PR2** permiso+banners, **PR3** undo tests, **PR4** polish+novedad tip. Target **main**.

## Affected Areas

- Modified: `oc_match/doc_refs.py`, `worker.py`, `compras_044`, factura model, `compras_alertas_service.py`, `AppLayout.jsx`, `TabRecepcionDeposito.jsx`
- Tests only: `recepcion_service.py` (D-UNDO-R already correct)
- New (gated): `novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md`

## Risks

- 044 already applied on PR1 DBs (Med) — amend 044; follow-up only if rewrite impossible
- Fewer factura recipients (High) — Admin assigns; novedad explains
- UNIQUE vs mixed-case (Med) — casefold-dedupe at seed/writeback

## Rollback Plan

Revert stacked PR commits. Downgrade unique/seed if a follow-up shipped. Unassign the permission to stop fan-out.

## Dependencies

- admin-ocs: catalog = DB; no admin-ocs code (`tmp-coord-compras-permiso-alertas.md`)
- Chain #1320→#1324; Gabe → sernafernando **main**
- `resolver_usuarios_con_algun_permiso`; `max_alertas_visibles`

## Success Criteria

- [ ] OC Match factura → row + chip on; no false missing-factura
- [ ] 044 seed never inserts >100 chars; UNIQUE `(pedido_id, numero)`
- [ ] Factura alerts only `administracion.ver_alertas_factura`; faltantes still responsable
- [ ] Compras banners capped with “+N más”
- [ ] Undo tests: 409 second undo, CC+`pagado_en` → pagado, 403
- [ ] Empty OC block “OC no encontrada en ERP”; 1-of-3 stays non-controlado
- [ ] Novedad draft shown to Gabe before commit
