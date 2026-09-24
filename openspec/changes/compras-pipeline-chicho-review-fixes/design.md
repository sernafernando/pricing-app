# Design: Compras Pipeline Chicho Review Fixes

## Amendment (Gabe 2026-09-23)

Phases 1–4 (Match alta, UNIQUE, permiso, banners, undo tests, empty OC) already landed. This amend **redefines “cargada”** and **moves the alert** from persist to a 5-minute ERP-check timer. D-WB-ALTA’s “insert + notify” is **superseded**: insert stays; notify does not.

## Technical Approach

Reuse typed `pedido_factura_documentos` as **constancia identity** (admin-ocs Text blobs cannot hold per-factura checks). Add check columns + PATCH. Dispatch pending alerts with a durable sweep and injectable `ahora`. Do not use in-process sleep. No admin-ocs code. Rewrite the novedad draft; Gabe reads before commit.

## Architecture Decisions

| ID | Option | Tradeoff | Decision |
|----|--------|----------|----------|
| D-WB-ALTA | Worker-only insert vs shared alta | Duplicate identity | **Landed.** After `apply_writeback`, same FOR UPDATE txn calls persist. Writeback stays text-only. `created_by_id` = `pedido.creado_por_id`. Casefold-skip. **Notify removed (see D-NO-PERSIST-ALERT).** |
| D-NO-PERSIST-ALERT | Keep notify-on-insert vs stop | Shipped tests assume notify | **`persist_factura_documento` / Match / manual POST MUST NOT call `notificar_factura_cargada`.** Row = constancia only. |
| D-CARGADA-COLS | Pedido-level flag vs per-row | Gabe: each factura | Per row: `cargada` bool default false, `cargada_marked_at` timestamptz null, `cargada_marked_by_id` FK usuarios null. Existing rows stay unchecked (no backfill). |
| D-ALERT-TIMER | `BackgroundTasks.sleep(300)` vs durable sweep | Sleep dies on restart | **`alerta_pendiente_hasta` timestamptz null** on the row. Check sets it to `ahora + FACTURA_CARGADA_ALERT_DELAY` (5 min). Uncheck nulls it. Sweep `disparar_alertas_factura_pendientes(session, ahora=)` selects `cargada AND alerta_pendiente_hasta <= ahora AND alerta_disparada_at IS NULL`, notifies, stamps `alerta_disparada_at`. Cron script + injectable `ahora` in tests. **Rejected:** in-process sleep. |
| D-TWO-WINDOWS | One 5-min clock vs two | Operator confusion | **Two constants, two clocks.** `FACTURA_UNDO_WINDOW` = DELETE row from `created_at`. `FACTURA_CARGADA_ALERT_DELAY` = pending alert from `cargada_marked_at`. DELETE of a row also cancels its pending alert (row gone). Uncheck never deletes the row. |
| D-CHIP-ERP | Row-count chip vs cargada chip | Gabe lock | `es_factura_cargada` / chips = **≥1 row with `cargada=true`**. Add `tiene_numero_factura` (≥1 row) for detalle / optional muted signal. List chip label stays “Factura” but meaning is **cargada**. |
| D-PATCH | New route vs reuse DELETE | Distinct verb | `PATCH /pedidos/{id}/factura-documentos/{row_id}` body `{ "cargada": bool }`. Permiso: `administracion.gestionar_ordenes_compra` (same as POST/DELETE). Recipients of the later alert stay `administracion.ver_alertas_factura`. |
| D-IDEMPOTENT | Reset timer on re-check vs no-op | Double-click | Check when already `cargada=true` → 200, **do not** reset `cargada_marked_at` / pending. Uncheck when already false → 200 no-op. Re-check after uncheck → **new** 5-min pending (clears `alerta_disparada_at`). |
| D-POST-FIRE-UNCHECK | Retract delivered vs leave | Gabe only specified pre-fire cancel | Uncheck **after** fire: clear `cargada`, leave delivered banners. Uncheck **before** fire: no notify. DELETE undo still retracts if a fire already happened (existing `retractar_factura_cargada`). |
| D-044 | New rev vs amend 044 | 044 not on main; some PR1 DBs applied | **Landed.** Amend `compras_044`. Do not re-amend. |
| D-047 | Hang after 045 vs amend 044 | 045 is current head | `compras_047_factura_cargada_erp` parent = `compras_045_pedido_compra_ocs`. Columns + index on `(alerta_pendiente_hasta)` where pending. |
| D-PERM | Keep D-FANOUT vs resolver | Titular/Admin lose auto-alerts | **Landed.** Recipients = resolver(`administracion.ver_alertas_factura`). Unchanged. |
| D-BANNER | Rotate compras vs cap | Rotation hides unpaid OK | **Landed.** Cap + “+N más”. |
| D-UNDO | Change service vs tests | D-UNDO-R already correct | **Landed** (recibido undo). Factura **DELETE** undo stays 5 min from `created_at`. |
| D-ERP-UI | Hide empty vs keep block | Honest link | **Landed.** |
| D-CHAIN | New PRs vs existing | Review budget | Phases 1–4 stay on #1320–#1324. **PR5** = D-NO-PERSIST-ALERT + D-CARGADA-COLS + D-ALERT-TIMER + D-PATCH + tests. **PR6** = FE checkbox/chip + novedad rewrite (Gabe gate). Same feature-branch-chain, target **main**. |
| D-READ-SEED | List-time GET write vs migrate/writeback | GET side effects | **Landed.** No GET seed. Seed creates constancia rows, **not** cargada. |

## Data Flow

```
Match / manual alta
  apply_writeback → facturas_documento token   (constancia text; no alert)
  persist_factura_documento → row              (constancia entity; NO notify)
       └─ chip "Factura cargada" stays OFF
       └─ detalle shows number + unchecked box

Administración PATCH cargada=true
  cargada=true, cargada_marked_at=ahora
  alerta_pendiente_hasta=ahora+5m
  chip ON immediately (ERP check, not “alert sent”)

  ┌─ uncheck before fire ─→ pending null; chip OFF; no Notificacion
  └─ sweep at/after fire ─→ notificar_factura_cargada
                              └─ resolver(administracion.ver_alertas_factura)
                                   └─ AppLayout cap + "+N más"

DELETE row (FACTURA_UNDO_WINDOW from created_at)
  cancel pending; retract fired notifs if any; 409 after window
```

## File Changes

| File | Action | Why |
|------|--------|-----|
| `backend/app/models/pedido_factura_documento.py` | Modify | `cargada`, `cargada_marked_at`, `cargada_marked_by_id`, `alerta_pendiente_hasta`, `alerta_disparada_at` |
| `backend/alembic/versions/compras_047_factura_cargada_erp.py` | Create | Parent `compras_045`; no backfill of `cargada` |
| `backend/app/services/pedidos_service.py` | Modify | Stop notify in persist; chip = cargada flags; `marcar_factura_cargada`; keep DELETE undo distinct |
| `backend/app/services/compras_alertas_service.py` | Modify | Sweep `disparar_alertas_factura_pendientes`; persist no longer calls notify |
| `backend/app/scripts/dispatch_factura_cargada_alerts.py` | Create | Cron entry; calls sweep (same pattern as other `sync_*` scripts) |
| `backend/app/routers/administracion_compras.py` | Modify | PATCH check/uncheck |
| `backend/app/schemas/pedido_compra.py` | Modify | Response fields; PATCH body; detalle list of factura rows |
| `backend/app/services/oc_match/worker.py` | Keep | Persist after writeback; notify already removed in persist |
| `backend/app/services/oc_match/doc_refs.py` | Keep | Text tokens only |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Checkbox per factura row; numbers as constancia |
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | Chip from `factura_cargada` (ERP) |
| `backend/tests/unit/test_pedido_factura_documentos.py` | Modify | Row ≠ cargada; Match chip-off; DELETE undo still `created_at` |
| `backend/tests/unit/test_compras_alertas_service.py` | Modify | No notify on alta; fire/cancel timer |
| `backend/tests/integration/test_oc_match_worker.py` | Modify | Row exists; chip off; zero `compras.factura_cargada` |
| `docs/modulos/compras-guia-usuario.md` | Modify | Constancia vs cargada; two 5-min windows |
| `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` | Rewrite | Gabe already saw wrong Match=cargada copy |

## Interfaces / Contracts

**PATCH** ` /administracion/compras/pedidos/{pedido_id}/factura-documentos/{row_id}`

- Auth: `require_permiso("administracion.gestionar_ordenes_compra")`
- Body: `{ "cargada": true | false }` (Pydantic v2)
- 200: updated row (`id`, `numero`, `cargada`, `cargada_marked_at`, `cargada_marked_by_id`)
- 404: missing pedido/row; 403: no permiso

**Sweep** `disparar_alertas_factura_pendientes(session, *, ahora=None) -> int`

- Idempotent. Rows with `alerta_disparada_at` set are skipped.
- Fan-out copy may say “marcada cargada en ERP” (not “identificada por Match”).

**Constants** (do not share)

- `FACTURA_UNDO_WINDOW = timedelta(minutes=5)` — DELETE row
- `FACTURA_CARGADA_ALERT_DELAY = timedelta(minutes=5)` — pending alert

**Chips payload**

- `factura_cargada`: ≥1 `cargada=true`
- `tiene_numero_factura`: ≥1 row (constancia; FE may show numbers in detalle without lighting the cargada chip)

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Persist/Match: row on, chip off, 0 notifs; check starts pending; uncheck cancels; sweep at T+5 fires; sweep at T+4:59 does not; re-check after uncheck new window; idempotent double-check; DELETE undo 409 at T+6 from `created_at` even if check clock differs | pytest; inject `ahora` |
| Integration | Worker persist no notif; PATCH 200/403/404; sweep cron function | existing compras fixtures |
| Frontend | Checkbox toggles PATCH; chip off when only numbers; chip on after check | vitest + RTL |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

`compras_047` after `compras_045`. Existing rows: `cargada=false`. Operators re-check ERP-loaded facturas. Revert PR5/PR6 to roll back. Unassign permiso to stop fan-out.

## Open Questions

- [x] Match write-back stays Text — **yes** (admin-ocs + Gabe).
- [x] Alert on persist — **no**.
- [x] Two 5-min windows — **keep both**.
- [ ] Confirm whether any PR1/PR4 DB already applied 044/045 before choosing 046 parent (apply-time; already resolved as 044→046→045). `compras_047` hangs on 045.
