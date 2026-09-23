# Design: Compras Pipeline Reqs Closure

## Technical Approach

Complete A1 on the existing resolver — no new `estado`, no Alembic. Require `texto`, stamp `faltantes_resuelto_en`, retract `compras.faltantes` by `item_id`, fan G31 with texto + Depósito link. BE `eje_procesal`/`tipo` list filters; FE resolver + no banner OK. Other gaps reuse DTOs and adjuntos `tipo=otro`.

## Architecture / Data Flow

```
PM Detalle (faltantes_sin_res)
  POST /pedidos/{id}/faltantes/resolver {texto}
       │ 422 empty │ 403 not writer │ 409 wrong estado / already stamped
       ▼
stamp; estado stays con_faltantes
  ├─ retractar_faltantes(item_id=P)
  └─ G31 to deposito.recibir_mercaderia
       copy = texto + DEEP_LINK_DEPOSITO
       codigo_producto = /administracion/compras?tab=deposito&pedido={id}

Depósito Ver → Recibidos → expand P → control
```

| Tab | Query |
|-----|--------|
| Por recibir | `estado=pagado` (+`,en_cuenta_corriente` if CC) + `tipo=mercaderia` |
| Recibidos | `eje_procesal=recibido,faltantes_con_res` |
| Controlados | `eje_procesal=controlado` |
| Con faltantes | `eje_procesal=faltantes_sin_res` |

`solo_deposito` still intersects mapped estados with `_ESTADOS_VISIBLES_DEPOSITO`.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Resolve | Stamp; keep `con_faltantes` | Reuses eje; new estado breaks events/chicho |
| Tabs | BE `eje_procesal` comma-OR | Client hide lies on totals; Recibidos = con_res home |
| G31 link | `?tab=deposito&pedido={id}` in `codigo_producto` | Page honors `tab`; Depósito must consume `pedido` |
| OK/dismiss | 409 on `/ok`, `/descartar`, `/bulk-descartar` | Campanita otherwise resurrects; snooze stays |
| Writers | responsable **or** `gestionar_ordenes_compra` | Depósito-only stamp retracts PM alert |
| Re-resolve | 409 if already stamped | No duplicate G31 |
| Empty texto | 422 | Same as `notificar_faltantes` |
| Photo | Adjuntos `otro`, upload-then-control | No `tipo=foto` / multipart control |
| Cargada badge | `factura_cargada` + `badgeControlado` | Numbers alone must not badge |
| Ident chips | All rows + `pedidos_documento` | CON-OC XOR hid factura/Admins-OC |
| OC chip | Vinculación; `#{poh}` if N>1 | GBP-missing already in Depósito copy |
| Tipo | Create selector; Por recibir `tipo=mercaderia` | Arrival already 409s servicio |

## File Changes

**Modify:** `recepcion.py` (required `texto`); `recepcion_service.py` (writer, 409 if stamped, retract→G31); `compras_alertas_service.py` (`retractar_faltantes`, G31 copy+link, reject close); `pedidos_service.py` (`aplicar_filtro_eje_procesal`); `notificacion_service.py` (optional `codigo_producto`); `administracion_compras.py` (resolver auth, list `eje_procesal`+`tipo`); `notificaciones.py` (409 OK/descartar/bulk). FE: `useRecepcionDeposito.js`, `ModalPedidoDetalle.jsx`, `AppLayout.jsx`, `TabRecepcionDeposito.jsx`, `TabPedidosCompra.jsx`, `ModalPedidoCompra.jsx`. Docs: `compras-guia-usuario.md`. Reuse `AdjuntosPanel` (`tipo=otro`). Tests below. **Create/Delete:** none. **No Alembic.**

## API Changes

`POST …/faltantes/resolver` `{texto}` required (blank 422). Auth `get_current_user`; writer = responsable **or** `gestionar_ordenes_compra` (depósito-only 403). 200 `{pedido_id, faltantes_resuelto_en}`; estado unchanged. 409 if not `con_faltantes` or stamp set.

`GET …/pedidos` adds `eje_procesal` (comma-OR) and `tipo`. Map: `faltantes_sin_res` = `con_faltantes AND stamp IS NULL`; `faltantes_con_res` = stamp set; others = existing estado sets.

`PATCH …/ok|descartar` and `POST …/bulk-descartar`: `compras.faltantes` → 409 (bulk fails closed). Snooze / factura / G31 OK unchanged. Create already takes `tipo`; control already takes `observaciones`.

## Sequence Notes

**PM resolve:** Detalle shows required textarea when `faltantes_sin_res`. POST → stamp → eje `faltantes_con_res` → retract banner → G31. Label “Faltantes con resolución”.

**Depósito execute:** Ver opens Recibidos, expands P. Optional obs + `POST …/adjuntos` `tipo=otro` **then** control. Control OK without evidence still succeeds → existing `controlado` path.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| PR >400 lines | Five chained slices |
| Campanita bypass | Guard descartar + bulk, not only `/ok` |
| Client tab hide | BE eje + tipo |
| Photo orphan | Upload-then-control |
| Chip wrap | 60ch + `title` |
| Chicho drift | Badge reads flag only; no timer edits |

## Test Strategy

| Layer | What | Where |
|-------|------|--------|
| Unit | 422/403/409; stamp; retract; G31 copy+link; snooze; eje/tipo SQL | `test_compras_alertas_service.py`, recepcion unit, `test_eje_procesal.py` |
| Integration | Resolver + tab lists + servicio excluded | `test_recepcion_deposito_endpoints.py` |
| FE | No-dismiss; form; tab params; badge; CON-OC chips; tipo; multi-OC | existing vitest files |

Keep chicho factura tests green. Do not amend `compras-pipeline-chicho-review-fixes`.

## Threat Matrix

N/A — no routing/shell/process/VCS-automation boundary.

## Migration / Rollout

None. Revert newest slice first. PR1 rollback: optional texto, old G31, dismissible OK, depósito writer.

## PR Chain (High 400-line risk)

1. **BE 15+17** — texto, retract, G31, 409, eje/tipo list, writers, tests.
2. **FE 15+17** — form, hook, no-dismiss, tab params, G31 land, eje label.
3. **Depósito ID** — #6 badge, #7/#12 chips, #3 guide.
4. **Control evidence** — #16 obs+photo.
5. **Tipo + OC labels** — #9, #19.

PR2 depends on PR1. PR3–5 after PR1; prefer after PR2 for FE locality.

## Non-goals / Do-not-regress

Do not amend chicho. No new estado, `tipo=foto`, GBP chip, novedad rewrite, email/Slack, ERP multi-factura join.

**Locks:** constancia ≠ cargada; no Match/persist alert; 5m cargada timer + uncheck cancel; two 5m windows; UNIQUE factura rows; `administracion.ver_alertas_factura`; Factura chip = cargada.

## Open Questions

None.
