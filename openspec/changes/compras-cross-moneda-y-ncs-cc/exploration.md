# Exploration: compras-cross-moneda-y-ncs-cc

Permitir imputaciones cross-moneda (OP ARS → pedido USD) con TC obligatorio + visibilidad de NCs aprobadas con saldo en el CC + acciones de imputar desde el CC.

## Current State

### A) Cross-moneda en imputaciones — hoy PROHIBIDA

- **`imputaciones_service.crear_imputacion`** (línea 142): inserta una imp sin validar cross-moneda. El comentario interno (líneas 196-201) dice explícitamente que la validación cross-moneda la hace el caller.
- **`_validar_moneda_consistente`** (línea 94): helper que rechaza cross-moneda si `origen.moneda != destino.moneda`. Está disponible pero NO se llama desde `crear_imputacion`.
- **`ordenes_pago_service._validar_items_misma_moneda_que_op`** (línea 203, agregado en PR #624): rechaza cross-moneda OP↔item. Llamado en 3 puntos: `crear` (L415), `editar` (L919, L927), `ejecutar_pago` (L725). Tira HTTP 400 si la moneda del pedido item != moneda OP.
- **`ejecutar_pago`** (líneas 742, 762, 777): graba la imp con `moneda_imputada=op.moneda`. La imp queda en la moneda de la OP (origen).
- **`cc_proveedor_service.aplicar_imputacion`** (línea 246): proyecta la imp a CC usando `imp.moneda_imputada` para el movimiento. HABER se genera en moneda de la imp (= moneda OP hoy).

### B) NCs en CC — invisibles

- **Endpoint `GET /ncs-locales`** (línea 3080 del router): paginado con filtros pero no hay flag específico para "disponibles para imputar" (estado aprobado/aplicada_parcial AND saldo_pendiente > 0).
- **TabCCProveedores.jsx**: no muestra NCs disponibles del proveedor. Solo muestra imputaciones ya aplicadas a pedidos.
- **Acciones desde CC**: solo "Nuevo pedido", "Nueva OP", "Nueva NC", "Pago Rápido", "Ajuste Manual". NO hay "Aplicar NC al pedido X" ni "Imputar pago al pedido X" directos por card de pedido.

## Affected Areas

### Backend

| Archivo | Por qué se toca |
|---|---|
| `backend/app/services/imputaciones_service.py` | Relaxar `_validar_moneda_consistente` para permitir cross-moneda CON TC obligatorio |
| `backend/app/services/ordenes_pago_service.py` | Cambiar `_validar_items_misma_moneda_que_op` → `_validar_items_cross_moneda_con_tc` (permite si OP tiene TC). `ejecutar_pago` debe convertir monto item ARS → USD usando TC y grabar imp en moneda destino |
| `backend/app/services/cc_proveedor_service.py` | Sin cambios estructurales — `aplicar_imputacion` ya usa `imp.moneda_imputada` (que ahora coincidirá con destino) |
| `backend/app/services/pedidos_service.py` | Agregar `calcular_tc_ponderado_pedido(pedido_id)` que computa promedio ponderado de imps USD del pedido |
| `backend/app/schemas/pedido_compra.py` | Agregar campo derivado `tipo_cambio_ponderado: Optional[Decimal]` a `PedidoCompraResponse` |
| `backend/app/routers/administracion_compras.py` | Nuevo endpoint `GET /ncs-locales/disponibles?proveedor_id=X` (o flag en endpoint existente) que filtra aprobadas/aplicada_parcial con saldo > 0. Endpoint `/cc-proveedor/{id}/por-pedido` incluye `tc_ponderado` y NCs aplicables |
| `backend/app/schemas/orden_pago.py` | El `OrdenPagoItem` puede tener `monto` en moneda OP O en moneda destino — clarificar contrato |

### Frontend

| Archivo | Por qué se toca |
|---|---|
| `frontend/src/components/compras/ModalOrdenPagoNueva.jsx` | Relaxar el confirm destructivo de cambio de moneda con items pre-cargados — ahora permitido con TC. Mostrar campo "TC para cross-moneda" cuando OP.moneda != items.moneda |
| `frontend/src/components/compras/TabCCProveedores.jsx` | Sección nueva "NCs disponibles del proveedor" en hero. Botones "Aplicar NC" y "Imputar pago" desde card de pedido en vista por-pedido |
| `frontend/src/components/compras/ModalAplicarNC.jsx` | Pre-cargar destino=pedido cuando se invoca desde CC |

### Tests

| Archivo | Por qué se toca |
|---|---|
| `backend/tests/unit/test_imputaciones_service.py:104` | `test_cross_moneda_raise_400` debe REINVERTIR la lógica: cross-moneda CON TC ahora pasa, sin TC sigue fallando |
| `backend/tests/unit/test_pedidos_vincular_factura.py:263, 520` | Tests `test_moneda_factura_distinta_a_pedido_400` siguen válidos (factura ERP ≠ pedido, distinto de cross-moneda OP) |
| `backend/tests/unit/test_ordenes_pago_service.py:1082-1157` | Tests existentes de cross-moneda caja-OP con TC override siguen válidos |
| Nuevos tests | `test_imputacion_cross_moneda_con_tc_ok`, `test_imputacion_cross_moneda_sin_tc_400`, `test_op_cross_moneda_genera_imp_en_moneda_destino`, `test_tc_ponderado_pedido_calcula_correctamente` |

## Approaches

### 1. **1 change único cross-moneda + NCs CC** — combinar A + B

Ambos features se cruzan en la UI del CC: el flujo "ver NC disponible → aplicarla al pedido USD pagando con OP ARS cross-moneda" requiere ambos juntos para ser útil.

- Pros:
  - Coherencia UX al primer ship
  - Tests integration cubren el flujo completo end-to-end
  - Un solo SDD/PR-cadena, no fragmentación
- Cons:
  - PR más grande (~1200 LOC backend + frontend)
  - Más riesgo de regresiones si algo falla
- Effort: **High** (~6-8 horas)

### 2. **2 sub-changes secuenciales**

- `compras-cross-moneda-imputaciones` (A primero): relaxar validación + ejecutar_pago + tests
- `compras-ncs-visibles-cc` (B después): NCs en hero del CC + botones "imputar"

- Pros:
  - Cada PR más chico (300-500 LOC c/u), revisable
  - Si A falla, B no se bloquea (solo cambia UI)
- Cons:
  - 2 ciclos de review/merge
  - Si user prueba A sin B → no ve el beneficio completo (no puede aplicar NCs desde el CC)
- Effort: **Medium x2** (~3-4h c/u)

### 3. **3 sub-changes (A + B1 + B2)**

- A: cross-moneda
- B1: NCs visibles en hero (read-only)
- B2: acciones imputar desde CC

- Pros: PRs muy chicos
- Cons: 3 ciclos de review, sobreingeniería
- Effort: **Low x3** (~2h c/u)

## Recommendation

**Opción 1 — 1 change único**. Justificación:

- Los 2 features sirven al mismo workflow del user ("quiero pagar este pedido USD con NC + OP ARS desde el CC"). Separarlos hace que el primer ship sea inútil sin el segundo.
- El cambio en `imputaciones_service` (relaxar validación) + tests es lo más complejo y ya está bien acotado. Los cambios en UI son aditivos (no modifican comportamiento existente).
- Por experiencia previa en el módulo, el user mergea rápido y prefiere ver el flujo completo de un saque (ya pasó con el rediseño compras-redesign-tabs y compras-redesign-pedidos).

## Risks

| Riesgo | Likelihood | Mitigation |
|---|---|---|
| `aplicar_imputacion` genera HABER en moneda destino (USD) pero la OP es ARS → saldo ARS del proveedor en CC queda sin contrapartida | Alta | El HABER USD es el correcto contablemente. El caja_movimiento ARS por OP es el flujo de plata real. Saldos por moneda separados → cada moneda cuadra. Documentar explícitamente |
| Reversal de imp cross-moneda: si la imp original es USD por 466.67 (con TC 1500), el reversal usa misma moneda y monto → DEBE 466.67 USD. ¿Pero el saldo ARS pagado? La OP sigue ejecutada en caja ARS, no se devuelve | Media | Reversal solo desimputa, no devuelve plata. Si user quiere devolver la plata, debe ANULAR la OP. Documentar en help text del modal |
| Tests existentes con cross-moneda fallarán (PR #624) | Cierta | Renombrar/reescribir tests para reflejar nueva semántica (cross-moneda con TC OK, sin TC 400) |
| TC ponderado calculado al vuelo en cada GET de pedido → N+1 si listado | Media | Batch helper similar al de saldos_pendientes (1 query agregado por pedido_ids) |
| NCs aplicada_parcial: tienen saldo > 0, son aplicables → mostrarlas también, no solo aprobadas | Alta | Filtro: estado IN ('aprobado', 'aplicada_parcial') AND saldo > 0 |
| Edge: pedido completamente pagado con NC (sin OP) — el approach del user dijo "se crea la OP igual" pero contablemente no tiene sentido si el monto es $0 | Media | Out of scope de este change. La aplicación de NC desde CC NO requiere crear OP — es imputación NC → pedido directa (endpoint /ncs-locales/{id}/aplicar ya existe) |

## Ready for Proposal

**Sí**. Confirmar con el orquestador:
- Approach recomendado: 1 change único combinando A + B
- Decisiones técnicas clave: `moneda_imputada` = moneda destino (no origen) en cross-moneda; TC obligatorio en cross-moneda; TC ponderado como campo derivado
- Edge case "NC cubre 100% del pedido sin OP" queda fuera de este change (se hace con el endpoint `/ncs-locales/{id}/aplicar` existente desde la UI del CC)

Siguiente paso: `sdd-propose compras-cross-moneda-y-ncs-cc`.
