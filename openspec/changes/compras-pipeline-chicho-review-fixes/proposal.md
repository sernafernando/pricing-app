# Proposal: Compras Pipeline Chicho Review Fixes

## Amendment (Gabe 2026-09-23) — authoritative

**Wrong (shipped / originally planned):** “factura cargada” = ≥1 row in `pedido_factura_documentos`; alert on persist (manual POST or OC Match).

**Right:**

| Concept | Meaning | Alert? |
|---------|---------|--------|
| Constancia | Factura / NV / pedido **numbers** identified by OC Match or typed in | **No** |
| Cargada | Per-**factura** ERP check by Administración (may be much later) | **Yes, after 5 min** if still checked |

1. Document numbers are constancia on the pedido only. **No alert** on upload, identify, persist, or Match write-back.
2. Each **factura** row can be marked **cargada** when loaded to ERP.
3. Check starts a **5-minute pending-alert timer**. After 5 minutes → in-app alert to `administracion.ver_alertas_factura`. Uncheck **before** fire → **cancel** the pending alert.
4. Chip **“Factura cargada”** follows ERP checks, not row presence.
5. Match write-back stays text constancia (admin-ocs confirmed). No alert from Match.

**Two distinct 5-minute windows (do not collapse):**

| Window | Clock starts | Action | If cancelled |
|--------|--------------|--------|--------------|
| **DELETE undo** (shipped) | Row `created_at` | Operator may DELETE the constancia row | After 5 min → HTTP 409; row stays |
| **Uncheck-before-alert** (this amend) | `cargada_marked_at` | Pending alert is scheduled | Uncheck before fire → no alert. Does **not** delete the row |

Coord (read, other worktree): `tmp-coord-factura-cargada-check.md` (read-only) under feature-admin-ocs. Ownership: check + timer + alert = **compras-ux**. Match stays append-only Text.

Phases 1–4 of this change already landed (Match rows, UNIQUE, permiso, banners, undo tests, empty OC). This amend **does not reopen** those except to **stop notify-on-persist**, **redefine the chip**, and **rewrite the novedad draft** Gabe already saw (wrong “Match = cargada”).

## Intent

Chicho reviewed PRs #1320–#1324. Close the Match write/read split and review holes, **then** implement Gabe’s ERP-check model so “cargada” is not confused with “número identificado”.

## Scope

### In Scope (original — landed)

- Shared alta from `apply_writeback` inserts `pedido_factura_documentos` same txn
- Amend `compras_044`: truncate/filter to 100, UNIQUE/dedupe
- Seed `administracion.ver_alertas_factura`; banner cap `+N más`
- Document D-UNDO-R; empty OC block; 1-of-3 test

### In Scope (this amend)

- Stop `notificar_factura_cargada` on `persist_factura_documento` / Match / manual alta
- Fields on factura rows: `cargada`, `cargada_marked_at` (and marker user)
- PATCH check/uncheck + 5-minute pending-alert semantics (cancel on uncheck)
- Chip from `cargada` flags; detalle checkbox per factura; separate “has number” vs “cargada”
- Tests: persist/Match do not alert; timer fire; timer cancel; two 5-min windows stay distinct
- Rewrite novedad draft (Gabe already saw the wrong Match=cargada copy)

### Out of Scope

- admin-ocs / OC Match code (write-back stays Text tokens)
- Checks on NV / pedido / `pedidos_documento` (constancia only)
- Auto-cargada from ERP `ct_transaction_id` / `numero_factura`
- Changing DELETE-undo window length or collapsing it into the alert timer
- `compras.*` permission codes; faltantes recipients; new PR chain name

## Capabilities

### New Capabilities

- None (same change folder)

### Modified Capabilities

- `compras-factura-documentos`: rows = constancia; `cargada` = ERP check; PATCH + timer; persist/Match do not notify
- `compras-pipeline-alerts`: factura alert fires **only** after 5 min on a still-checked row; recipients unchanged
- `pedidos-compra`: chip “Factura cargada” = ≥1 `cargada`; optional “has number” signal
- `recepcion-estados` / `vincular-oc` / `recepcion-deposito`: unchanged from landed Phases 3–4

## Approach

Keep typed rows (already the per-factura entity admin-ocs said Text cannot provide). Add check columns + PATCH. Persist stays identity-only. Dispatch pending alerts via a sweep with injectable `ahora` (same test style as DELETE undo). Land as **PR5** (backend) + **PR6** (FE + novedad rewrite) stacked on the existing #1320–#1324 chain. Target **main**.

## Affected Areas

- Landed: worker persist, `compras_044`/`046`, alert resolver, AppLayout cap, undo tests, TabRecepcionDeposito
- Amend: `pedidos_service.py` (stop notify; chip query; PATCH service), `pedido_factura_documento.py`, new Alembic `compras_047`, `compras_alertas_service.py`, `administracion_compras.py`, schemas, `ModalPedidoDetalle` / `TabPedidosCompra`, tests, novedad draft, guía

## Risks

- Operators who already treated “Match done = cargada” will see the chip go off until they check (High) — novedad + guía must say this explicitly
- In-process `BackgroundTasks.sleep(300)` would drop pending alerts on restart (High) — **rejected**; durable columns + sweep
- Existing rows default `cargada=false` (Med) — no silent backfill
- Confusing DELETE undo 5 min with alert-timer 5 min (Med) — specs/UI copy must name both

## Rollback Plan

Revert PR5/PR6. Downgrade `compras_047` drops check columns. Unassign `administracion.ver_alertas_factura` to stop fan-out. DELETE undo remains.

## Dependencies

- admin-ocs: Match write-back = Text only; no check/timer there (`tmp-coord-factura-cargada-check.md`)
- Existing chain #1320–#1324; Gabe → sernafernando **main**
- `resolver_usuarios_con_algun_permiso`; `FACTURA_UNDO_WINDOW` stays a **different** constant

## Success Criteria

- [ ] Persist / Match / manual alta: row (constancia) exists; **zero** factura alerts; chip **off** until a check
- [ ] PATCH `cargada=true` starts 5-min pending; after 5 min + sweep → alert to permission holders
- [ ] PATCH `cargada=false` before fire → **no** alert; chip off
- [ ] Chip “Factura cargada” follows `cargada` flags, not row count
- [ ] DELETE undo 5 min still keyed off `created_at`; alert timer keyed off `cargada_marked_at`
- [ ] Novedad draft rewritten (not the Match=cargada text Gabe already saw); still **no commit until Gabe reviews**
