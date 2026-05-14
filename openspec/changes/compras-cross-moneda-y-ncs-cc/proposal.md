# Proposal: Compras Cross-Moneda + NCs Visibles en CC

## Intent

Dos problemas reales reportados:

1. **Cross-moneda OP↔pedido se rompía**: pedidos USD pagados con caja ARS no se podían imputar — `_validar_items_misma_moneda_que_op` (PR #624) y `_validar_moneda_consistente` rechazaban con HTTP 400. El user labura con caja ARS pero compra mercadería USD; la prohibición lo bloqueaba.
2. **NCs aprobadas con saldo del proveedor eran invisibles desde el CC**: para imputar una NC al pedido había que ir a otro tab, identificar el pedido manualmente, abrir modal. Flujo lento, propenso a error.

Ambos features confluyen en el mismo workflow: "quiero pagar este pedido USD con NC parcial + OP ARS cross-moneda desde el CC". Separarlos hace inútil el primer ship.

## Scope

### In Scope

**Backend**
- Relaxar `_validar_moneda_consistente` en `imputaciones_service` para permitir cross-moneda CON TC obligatorio.
- Cambiar `_validar_items_misma_moneda_que_op` → `_validar_items_cross_moneda_con_tc` en `ordenes_pago_service`: permite OP ARS con items USD si la OP trae TC.
- `ejecutar_pago` graba la imp en moneda destino (USD para pedido USD), convirtiendo monto ARS→USD con TC de la OP.
- Cada OP tiene su propio TC; no se reutiliza entre OPs del mismo pedido.
- Campo derivado server-side `tipo_cambio_ponderado` en `PedidoCompraResponse` = `sum(monto_ars_imps) / sum(monto_usd_imps)`. NO persistido. Calculado al vuelo con batch helper para evitar N+1.
- Endpoint nuevo (o flag en existente): `GET /ncs-locales/disponibles?proveedor_id=X` que filtra NCs con `estado IN ('aprobado', 'aplicada_parcial') AND saldo_pendiente > 0`.
- Endpoint `/cc-proveedor/{id}/por-pedido` enriquecido con `tc_ponderado` y `ncs_aplicables` por proveedor.

**Frontend**
- `ModalOrdenPagoNueva.jsx`: relaxar el confirm destructivo de cambio de moneda con items pre-cargados; mostrar campo "TC para cross-moneda" cuando `OP.moneda != items.moneda`.
- `TabCCProveedores.jsx`: sección "NCs disponibles" en hero del CC mostrando NCs aprobadas con saldo del proveedor. Botones "Aplicar NC" e "Imputar pago" en cada card de pedido (vista por-pedido).
- `ModalAplicarNC.jsx`: pre-cargar destino=pedido cuando se invoca desde un card del CC.

**Tests**
- Invertir lógica de `test_cross_moneda_raise_400` (ahora con TC pasa, sin TC sigue 400).
- Nuevos: `test_imputacion_cross_moneda_con_tc_ok`, `test_imputacion_cross_moneda_sin_tc_400`, `test_op_cross_moneda_genera_imp_en_moneda_destino`, `test_tc_ponderado_pedido_calcula_correctamente`.
- Mantener tests de cross-moneda caja↔OP con TC override (PR #624) — son ortogonales.

### Out of Scope

- **NC cubre 100% del pedido sin generar OP**: ya existe `/ncs-locales/{id}/aplicar`. No se toca en este change.
- **Migración de datos históricos**: pedidos viejos quedan con su semántica original. No se reescriben imps existentes.
- **Reversal de imp cross-moneda con devolución de plata**: el reversal solo desimputa, no devuelve fondos. Si user quiere devolver, debe ANULAR la OP. Solo se documenta en help text.
- **TC promedio del proveedor histórico**: el campo `tc_ponderado` es por pedido, no por proveedor.
- **Saldos del CC convertidos a moneda única**: cada moneda se mantiene en su balance separado (USD y ARS no se mezclan en el saldo agregado).

## Approach

### Decisiones técnicas clave (aprobadas, no reabrir)

1. **`moneda_imputada` = moneda destino (no origen)**. En cross-moneda OP ARS → pedido USD, la imp se graba `moneda_imputada=USD, monto_imputado=monto_ars/tc`. Esto hace que el HABER del CC quede en USD (la moneda real de la deuda) sin tener que tocar `cc_proveedor_service.aplicar_imputacion`.
2. **TC obligatorio en cross-moneda, por OP**. Cada OP trae su propio TC. No se hereda ni promedia entre OPs.
3. **TC ponderado del pedido = campo derivado server-side, NO persistido**. Cálculo: `sum(monto_origen_ars) / sum(monto_destino_usd)` sobre las imps del pedido. Se devuelve en `PedidoCompraResponse`. Batch helper para listados.
4. **HABER del CC en moneda destino; caja sigue por moneda OP**. El movimiento de caja ARS por la OP es flujo real de plata; el HABER USD es la deuda contable. Cada moneda cuadra contra su propia base.
5. **Append-only sagrado**. Ninguna mutación destructiva en `imputaciones`, `cc_proveedor_movimientos`, `compras_eventos`. Las correcciones se hacen con reversal + nueva imp.

### Estructura del cambio

```
imputaciones_service._validar_moneda_consistente
  └─ acepta TC opcional; sin TC + cross-moneda → 400; con TC + cross-moneda → OK

ordenes_pago_service._validar_items_cross_moneda_con_tc
  └─ reemplaza _validar_items_misma_moneda_que_op
  └─ permite OP.moneda != item.moneda si OP.tipo_cambio is not None

ordenes_pago_service.ejecutar_pago
  └─ si cross-moneda: monto_imputado = item.monto / op.tipo_cambio (redondeo a 2)
  └─ moneda_imputada = item.pedido.moneda (no op.moneda)

pedidos_service.calcular_tc_ponderado_pedido(pedido_id) / _batch(pedido_ids)
  └─ helper nuevo. Devuelve Decimal o None si no hay imps cross-moneda.

PedidoCompraResponse.tipo_cambio_ponderado: Optional[Decimal]
  └─ schema field derivado, populado por el router.

GET /ncs-locales/disponibles?proveedor_id=X
  └─ filtro estado IN ('aprobado', 'aplicada_parcial') AND saldo > 0
```

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/imputaciones_service.py` | Modified | Relaxar `_validar_moneda_consistente`; aceptar `tipo_cambio` opcional |
| `backend/app/services/ordenes_pago_service.py` | Modified | Renombrar validador; `ejecutar_pago` convierte ARS→USD con TC |
| `backend/app/services/pedidos_service.py` | Modified | Nuevo `calcular_tc_ponderado_pedido` + batch helper |
| `backend/app/services/cc_proveedor_service.py` | Unchanged | Ya usa `imp.moneda_imputada` (ahora coincide con destino) |
| `backend/app/schemas/pedido_compra.py` | Modified | Agregar `tipo_cambio_ponderado: Optional[Decimal]` |
| `backend/app/schemas/orden_pago.py` | Modified | Clarificar contrato: `OrdenPagoItem.monto` en moneda OP origen |
| `backend/app/routers/administracion_compras.py` | Modified | Endpoint `GET /ncs-locales/disponibles`; enriquecer `/cc-proveedor/{id}/por-pedido` con `tc_ponderado` y `ncs_aplicables` |
| `frontend/src/components/compras/ModalOrdenPagoNueva.jsx` | Modified | Habilitar cross-moneda con campo TC |
| `frontend/src/components/compras/TabCCProveedores.jsx` | Modified | Hero con NCs disponibles; botones "Aplicar NC" / "Imputar pago" por card |
| `frontend/src/components/compras/ModalAplicarNC.jsx` | Modified | Pre-cargar pedido destino desde CC |
| `backend/tests/unit/test_imputaciones_service.py` | Modified | Invertir `test_cross_moneda_raise_400` |
| `backend/tests/unit/test_ordenes_pago_service.py` | Modified + New | Mantener cross-moneda caja↔OP; nuevos tests cross-moneda OP↔pedido |

## Impacto en comportamiento existente

- **Endpoints con cambio de contrato (no breaking, aditivo)**:
  - `POST /ordenes-pago` y `PUT /ordenes-pago/{id}`: ya no rechazan cross-moneda OP↔item si la OP trae `tipo_cambio`. Sin TC, sigue 400.
  - `POST /ordenes-pago/{id}/ejecutar`: las imps generadas pueden tener `moneda_imputada != op.moneda` (antes siempre coincidía). Consumidores que asumían igualdad deben recalibrar.
  - `GET /pedidos-compra/{id}` y listados: incluyen `tipo_cambio_ponderado` (campo nuevo, opcional, null para pedidos same-moneda).
  - `GET /cc-proveedor/{id}/por-pedido`: incluye `tc_ponderado` por pedido y `ncs_aplicables` por proveedor (campos nuevos).
- **Tests que rompen** (esperado):
  - `test_imputaciones_service.test_cross_moneda_raise_400` → invertir aserciones.
- **Semántica `moneda_imputada`**: antes = moneda OP origen; ahora = moneda pedido destino. Reportes que agregan por `moneda_imputada` ahora suman por moneda de la deuda, no por moneda de pago — esto es lo correcto contablemente.

## Risks

| Riesgo | Likelihood | Mitigation |
|--------|------------|------------|
| `aplicar_imputacion` genera HABER USD pero la OP es ARS → balance ARS del proveedor sin contrapartida directa | High | Es correcto: HABER USD = deuda contable (real); movimiento caja ARS = flujo de plata. Cada moneda cuadra independiente. Documentar en help text del modal y en el README del módulo |
| Reversal de imp cross-moneda no devuelve plata (la OP sigue ejecutada en caja ARS) | Med | Reversal solo desimputa. Para devolver plata: anular la OP. Documentar en tooltip del botón "Reversar" |
| TC ponderado calculado al vuelo → N+1 en listado de pedidos | Med | Batch helper `calcular_tc_ponderado_pedido_batch(pedido_ids)` con 1 query agregada, espejo del patrón ya usado para saldos pendientes |

## Rollback Plan

Cambio es aditivo en BD (no hay migraciones — `tipo_cambio_ponderado` es derivado, no columna). Rollback = revertir el PR.

Imputaciones cross-moneda creadas durante el período del PR:
- Si se revierte: las imps existentes quedan en BD con `moneda_imputada=USD` y OP ARS. El CC las sigue mostrando correctamente porque `aplicar_imputacion` no cambió.
- Listados de pedidos: el campo `tipo_cambio_ponderado` desaparece del response (frontend ya tolera campos opcionales).
- Para volver a prohibir cross-moneda hacia adelante: el `_validar_*` original se restaura con el revert del PR.

No hay riesgo de corrupción de datos por append-only.

## Dependencies

- Ninguna externa. Todo está en el módulo `compras`.
- Requiere que las OPs ya tengan campo `tipo_cambio` (existe desde PR #624 para caja↔OP cross-moneda — se reutiliza).

## Success Criteria

- [ ] Crear OP ARS para pedido USD con TC → se crea sin 400.
- [ ] Ejecutar esa OP → imp queda con `moneda_imputada=USD`, monto convertido correctamente.
- [ ] CC del proveedor muestra el HABER en USD y reduce la deuda USD del pedido.
- [ ] Caja ARS registra la salida en ARS (sin tocar saldo USD).
- [ ] `GET /pedidos-compra/{id}` devuelve `tipo_cambio_ponderado` correcto cuando hay imps cross-moneda; `null` cuando todas son same-moneda.
- [ ] Hero del CC muestra NCs aprobadas con saldo del proveedor seleccionado.
- [ ] Botón "Aplicar NC" en card del pedido abre `ModalAplicarNC` con pedido pre-cargado.
- [ ] Botón "Imputar pago" en card del pedido abre `ModalOrdenPagoNueva` con pedido pre-cargado.
- [ ] Tests unit nuevos pasan; `test_cross_moneda_raise_400` reescrito pasa.
- [ ] Flujo end-to-end manual: pedido USD $1000, NC $300 aplicada, OP ARS $1.000.000 con TC 1500 → saldo pendiente pedido = $33.33 USD.
