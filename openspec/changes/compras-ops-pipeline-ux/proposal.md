# Proposal: Compras Operator Pipeline UX

## Intent

Operators track Pedidos → pago → Depósito in spreadsheets because lists hide OC / factura / Match and mix finance with logistics. Ship in-app visibility, alerts, Depósito UX, and multi-OC. ERP multi-factura stays deprecated/untouched.

## Scope

### In Scope
- PR1 model + Pedidos/OPs visibility; PR2 alerts; PR3 Depósito UX; PR4 multi-OC
- `docs/modulos/compras-guia-usuario.md`; prod deploy (Chicho)

### Out of Scope
- ERP multi-factura; email/Slack (in-app only)
- Rename `aprobado` → Pendiente; procesal states that embed sin/con OC

## Capabilities

### New Capabilities
- `compras-factura-documentos`: normalized rows (option A) seeded from `facturas_documento`; nonempty doc number; 5-min undo
- `compras-pipeline-alerts`: stackable banner + campanita; factura fan-out; faltantes → responsable + G31 depósito ack

### Modified Capabilities
- `pedidos-compra`: tipo mercadería|servicio (default mercadería; PM create, admin edit); `responsable_id` (default/backfill `created_by`; editors admin+creator); chips OC/factura/Match; procesal axis; logistic states on Pedidos
- `ordenes-pago`: OPs column lists all linked Pricing `P-…` numbers
- `recepcion-deposito`: Por recibir = pagado default + CC toggle; AND filters (proveedor, pedido, Pricing `P-…`, factura, empresa); docs→adjuntos; hide complete faltantes lines; obs/photo optional
- `recepcion-estados`: undo recibido; `n_a_servicio`; controlado iff all OCs done
- `vincular-oc`: unlimited OCs; single-pedido N blocks; add without replace; servicio ⇒ no OC

## Approach

Reuse `AlertBanner` + notificaciones. “Cargada” = rows, not `ct_transaction` multi-link. Seed from `facturas_documento` (#1314/#1317); keep `pedidos_documento` write-once. Alert copy: Pricing `P-…` + proveedor + factura nº (never `pedidos_documento`). Recipients: titular ∪ sub-PM ∪ Admin ∪ Gerente; per-user OK. Faltantes: snooze 1h from mark; free text; deep-link detalle+observaciones; resolution → all `deposito.recibir_mercaderia`. Procesal: `n_a_servicio|por_recibir|recibido|faltantes_sin_res|faltantes_con_res|controlado`. Rebase `upstream/main` (1314/1316/1317) before apply.

## Affected Areas

- Modified: `pedido_compra.py`, `recepcion_service.py`, compras/alertas routers, Compras tabs, `AlertBanner.jsx`
- Modified: `docs/modulos/compras-guia-usuario.md`

## Risks

- Worktree behind main (High) → rebase first
- Oversized PR (High) → four chained slices
- Token seed edges (Med) → spec parse; keep raw field
- Alert over-notify (Med) → per-user OK; 5-min undo

## Rollback Plan

Revert each PR. Downgrade Alembic (tipo/responsable/factura-rows/multi-OC). Disable alert fan-out. Depósito toggles are UI-only. ERP matching unchanged.

## Dependencies

- `facturas_documento`, `pedidos_documento` on main
- `AlertBanner` + campanita; `deposito.recibir_mercaderia`; `marcas_pm`
- Rebase `upstream/main` before apply

## Success Criteria

- [ ] Pedidos show chips + logistic/procesal states; servicio skips OC
- [ ] Factura = rows; alert `P-…` + proveedor + factura nº; titular ∪ sub-PM ∪ Admin ∪ Gerente; per-user OK; 5-min undo
- [ ] Faltantes → responsable; 1h snooze; free text; deep-link + observaciones; resolution → all `deposito.recibir_mercaderia`
- [ ] Depósito Por recibir = pagado default; CC toggle; undo recibido; AND filters
- [ ] Multi-OC: N blocks; add without replace; controlado iff all OCs done
- [ ] Guide updated; in-app only; prod (Chicho)
