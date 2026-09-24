# Proposal: Compras Pipeline Reqs Closure

## Intent

Close residual Gabe gaps #15+#17, #6, #16, #9, #7/#12, #3, #19 after archived `compras-ops-pipeline-ux`. Do not amend `compras-pipeline-chicho-review-fixes`. Do not regress constancia≠cargada / no Match alert / 5m cargada timer / chicho locks.

## Scope

### In Scope
- A1 resolver: required `texto`; stamp `faltantes_resuelto_en`; keep `estado=con_faltantes`; retract `compras.faltantes`; G31 PM texto + Depósito deep-link; OK→409; Con faltantes=`faltantes_sin_res`; Recibidos includes `faltantes_con_res`; eje “Faltantes con resolución”; writers=responsable OR `administracion.gestionar_ordenes_compra` (drop `deposito.recibir_mercaderia`)
- #6 Cargada badge from `factura_cargada` (Controlado family)
- #16 Optional obs+photo on control incl. OK; adjuntos `tipo='otro'`
- #9 FE tipo on create; exclude `servicio` from Por recibir
- #7/#12 Factura + `pedidos_documento` chips on all Depósito rows incl. CON-OC
- #3/#19 OC chip=vinculación (document); compact Pedidos `ocs[]` labels when N>1
- Update `compras-guia-usuario.md`

### Out of Scope
New estado; `tipo=foto`; GBP-exists chip; novedad rewrite (Gabe last); chicho timer/alert edits; email/Slack; ERP multi-factura.

## Capabilities

### New Capabilities
None

### Modified Capabilities
- `compras-pipeline-alerts`: retract only on resolve; OK→409; G31 MUST include PM texto + Depósito deep-link
- `recepcion-estados`: keep `estado=con_faltantes`; required `texto`+stamp; writer perms; tab/eje split
- `recepcion-deposito`: Cargada badge; ident chips all rows; Por recibir excludes servicio; control-OK obs/photo `tipo='otro'`
- `pedidos-compra`: create tipo selector; eje label; compact multi-OC labels; OC chip=vinculación

## Approach

A1: stamp + required texto (no new estado). Retract by `item_id`. G31 → `deposito.recibir_mercaderia` with texto and `?tab=deposito&pedido={id}`. FE hides dismiss. BE eje/`tipo=mercaderia` filters. Photo via existing adjuntos (upload-then-control).

Chained PRs (400-line risk **High**): BE 15+17 → FE 15+17 → Depósito ID (6,7/12,3) → control photo (#16) → tipo+OC labels (9,19).

## Affected Areas

`recepcion_service.py`, `recepcion.py`, `compras_alertas_service.py`, `notificaciones.py`, `administracion_compras.py`, `AppLayout.jsx`, `ModalPedidoDetalle.jsx`, `useRecepcionDeposito.js`, `TabRecepcionDeposito.jsx`, `TabPedidosCompra.jsx`, `ModalPedidoCompra.jsx`, `compras-guia-usuario.md`.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Single PR >400 lines | High | Five chained slices |
| Campanita OK resurrects | Med | Same 409; snooze stays |
| Client-only tab hide | Med | BE eje filter |
| Depósito writer / photo orphan | Med | Drop writer; upload-then-control; badge reads flag only |

## Rollback Plan

Revert newest slice first. PR1 restores optional texto, old G31, dismissible OK, depósito writer. No new Alembic.

## Dependencies

Archived `compras-ops-pipeline-ux` + chicho locks. Existing resolver, stamp, `eje_procesal`, `AlertBanner`, adjuntos `tipo='otro'`.

## Success Criteria

- [ ] Resolver requires texto; stamps; retracts; G31 texto + Depósito deep-link; OK→409
- [ ] Con faltantes=`faltantes_sin_res`; Recibidos includes `faltantes_con_res`; label “Faltantes con resolución”; writers=responsable OR `gestionar_ordenes_compra`
- [ ] Cargada badge; factura+`pedidos_documento` on all Depósito rows; control-OK obs/photo `tipo='otro'`; tipo on create; Por recibir excludes servicio
- [ ] OC chip=vinculación (guide); compact `#{poh}` when N>1; no chicho regression; novedad deferred
