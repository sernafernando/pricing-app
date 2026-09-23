# Design: Compras Operator Pipeline UX

## Technical Approach

Four chained PRs on FastAPI / SQLAlchemy / Pydantic v2 / React CSS Modules. Reuse `pedidos_service`, `recepcion_service`, `crear_notificaciones_para_permisos`, `AlertBanner`, `NotificationBell`, `compras_adjuntos`, `compras_eventos`. ERP multi-link untouched. Procesal is derived DTO `eje_procesal`. Spec `created_by` → `creado_por_id`. **Apply gate:** rebase `upstream/main` (1314/1316/1317) before Alembic so `facturas_documento` exists.

## Architecture Decisions

| ID | Option | Tradeoff | Decision |
|----|--------|----------|----------|
| D-FACT | JSON vs rows vs ERP | JSON unqueryable; ERP deprecated | Table `pedido_factura_documentos`. Cargada ⇔ ≥1 row. Keep raw `facturas_documento`. `pedidos_documento` write-once, never identity. |
| D-FANOUT | No `marca_id` on pedido | Inferring marca invents scope | Broadcast: active `marcas_pm` ∪ `marca_sub_pm` ∪ `rol_codigo ∈ {ADMIN,GERENTE,SUPERADMIN}`. Dedup `user_id`. |
| D-BANNER | `alertas` rows vs `notificaciones` | `alertas` is CMS+rotation | One `Notificacion`/recipient. `AppLayout` stacks unread `compras.*` (no rotation, no `localStorage`). Campanita unchanged. In-app only. |
| D-SNOOZE | New column vs reuse | Shared-table migration | No column. Snooze → `REVISADA` + `notas_revision=snooze`. Hide while `now < fecha_creacion + 1h` (mark, not click). Then reappear until `DESCARTADA`. |
| D-SINOC | New action vs state routing | Spec deferred | Keep `confirmar_pedido_sin_oc` routing. `faltantes_texto` required if `completo=False`; `observaciones` always optional. |
| D-MULTI | Extra header cols vs relation | Header cannot hold N | `pedido_compra_ocs` SoT. Copy existing triple. Header `oc_*` = first-link cache; PR4 writers update both. |
| D-UNDO-R | Always `pagado` vs restore | CC arrival exists | `recibido` → `en_cuenta_corriente` if `op_cuenta_corriente_id` and not `pagado_en`, else `pagado`. Event `recepcion_undo_recibido`. Keep sentinels. |
| D-PERMS | New codes vs reuse | Extra seed | None new. Factura/vincular/create: `administracion.gestionar_ordenes_compra`. Tipo after create + any responsable: `ADMIN`/`SUPERADMIN`. Creator edits own `responsable_id`. Recepcion/undo/G31: `deposito.recibir_mercaderia`. |

## Data Flow

```
PR1 POST factura row → table + chips
PR2      └─ fan-out Notificacion → Banner + Bell
           undo≤5m → DELETE row + DESCARTADA
           faltantes → responsable; snooze mark+1h
           resolver → G31 crear_notificaciones_para_permisos
PR3 listar_pedidos AND ILIKE → Depósito (pagado default + CC toggle)
PR4 POST vincular-oc → INSERT (no replace) → N blocks; last OC → controlado
```

`eje_procesal`: `servicio`→`n_a_servicio`; `pagado`/`en_cuenta_corriente`→`por_recibir`; `recibido`→`recibido`; `con_faltantes` + null `faltantes_resuelto_en`→`faltantes_sin_res`; set →`faltantes_con_res`; `controlado`→`controlado`. Do not rename `aprobado`.

## File Changes

| File | Action | Why |
|------|--------|-----|
| `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` | Create | `tipo`+ck; `responsable_id` FK backfill `creado_por_id` NOT NULL; `faltantes_resuelto_en`; factura table; seed `;` tokens. (044: main already has `compras_042`/`compras_043`.) |
| `backend/alembic/versions/compras_045_pedido_compra_ocs.py` | Create | Relation + copy triple; unique `(pedido_id,oc_*)`; index `oc_poh_id`. (045: 042/043/044 already used.) |
| `backend/app/models/pedido_factura_documento.py` | Create | `pedido_id`, nonempty `numero`, `created_at`, `created_by_id`. |
| `backend/app/models/pedido_compra_oc.py` | Create | N triples. |
| `backend/app/services/compras_alertas_service.py` | Create | Fan-out, copy `P-…`+proveedor+nº, retract, snooze, G31. Tipos `compras.factura_cargada` / `faltantes` / `faltantes_resuelto`. |
| `backend/app/models/pedido_compra.py` | Modify | New cols + rels. |
| `backend/app/schemas/pedido_compra.py` | Modify | `tipo`, `responsable_id`, `eje_procesal`, chips, factura rows. |
| `backend/app/schemas/orden_pago.py` | Modify | `pedidos_numeros: list[str]`. |
| `backend/app/schemas/recepcion.py` | Modify | Optional obs; required `faltantes_texto` if incomplete; undo. |
| `backend/app/services/pedidos_service.py` | Modify | Defaults/gates; factura CRUD+5m undo; add-not-replace; servicio 409; chips. |
| `backend/app/services/recepcion_service.py` | Modify | Undo; servicio 409; all-OC saldos/estado; resolve faltantes. |
| `backend/app/routers/administracion_compras.py` | Modify | New routes; list `q_*` AND; OP batch P- numbers. |
| `backend/app/api/endpoints/notificaciones.py` | Modify | OK + snooze; hide-until-mark+1h. |
| `frontend/src/components/AppLayout.jsx` | Modify | Stack `compras.*` banners; OK→DESCARTADA. |
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | Chips + `eje_procesal`. |
| `frontend/src/components/compras/TabOrdenesPago.jsx` | Modify | All `P-…`. |
| `frontend/src/components/compras/TabRecepcionDeposito.jsx` | Modify | Pagado+CC; AND filters; hide saldo 0; undo; Docs=adjuntos; N blocks; optional obs/photo. |
| `frontend/src/hooks/useRecepcionDeposito.js` | Modify | Undo, resolver, `q_*`. |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Factura rows; tipo/responsable; `?focus=observaciones`. |
| `frontend/src/components/compras/ModalVincularOC.jsx` | Modify | Add without replace; servicio empty. |
| `docs/modulos/compras-guia-usuario.md` | Modify | Operator HOW. |

## Interfaces / Contracts

```
POST   /pedidos/{id}/factura-documentos          {numero}     201|422
DELETE /pedidos/{id}/factura-documentos/{rid}    undo ≤5m     204|409
POST   /pedidos/{id}/faltantes/resolver          {texto?}     200 → G31
POST   /pedidos/{id}/recepcion/deshacer-recibido              200|409
PATCH  /notificaciones/{id}/ok | /snooze
# vincular-oc adds row; duplicate 409; servicio 409
# GET /pedidos?estado=&q_proveedor=&q_numero=&q_factura=&q_empresa=  AND ILIKE
```

Chips: OC = relation count or header `oc_poh_id`; factura = row exists; Match = latest `compras_oc_match_jobs.status`. Photo = adjuntos `tipo='otro'`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Seed; empty nº 422; 5m undo; `eje_procesal`; fan-out; snooze clock; all-OC controlado; servicio 409 | pytest + `freezegun` |
| Integration | Retract; G31 permiso; AND filters; undo; OP P- list; add-without-replace | compras/recepcion fixtures |
| Frontend | Chips vs procesal; pagado+CC; hide saldo 0; N blocks; banner OK | vitest + RTL |

## Threat Matrix

N/A — no routing, shell, VCS/PR, or process-integration boundary.

## Migration / Rollout

Rebase `upstream/main` first. `compras_044` (PR1; 042/043 already on main) then `compras_045` for multi-OC (PR4). Downgrade drops tables/cols. Skip service to disable fan-out. PRs to `develop`. Chicho deploys.

## Open Questions

- None. D-SINOC kept; fan-out locked without `marca_id`.
