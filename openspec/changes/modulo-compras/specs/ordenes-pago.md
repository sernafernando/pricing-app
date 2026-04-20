# Spec Delta — Órdenes de Pago

**Change:** modulo-compras
**Capability:** ordenes-pago
**Status:** draft

## Purpose

Modelado de la orden de pago (OP) como documento contable intermedio entre el pedido aprobado y la salida real de plata de caja. Soporta múltiples modos de imputación (específica / a cuenta / mixta) y al marcarse como pagada dispara integración con Cajas y el libro mayor de CC proveedor de forma atómica.

## ADDED Requirements

### Requirement: REQ-OP-001 — Modelo `ordenes_pago`

**Priority:** must
**Type:** functional

El sistema MUST implementar el modelo `ordenes_pago` con los siguientes campos:
- `id` (PK)
- `numero` (VARCHAR único por `(tipo='orden_pago', empresa_id, año)`, formato `OP-01-2026-00001` — ver `numeracion-correlativa`)
- `empresa_id` (FK NOT NULL)
- `proveedor_id` (FK NOT NULL)
- `moneda` (VARCHAR NOT NULL, `ARS` | `USD`)
- `monto_total` (NUMERIC NOT NULL — suma de imputaciones + remanente a cuenta)
- `tipo_cambio` (NUMERIC NULL — usado si `moneda='USD'` y se paga desde caja ARS)
- `modo_imputacion` (VARCHAR NOT NULL, `especifica` | `a_cuenta` | `mixta`)
- `estado` (VARCHAR NOT NULL DEFAULT `pendiente`, `pendiente` | `pagado` | `anulado`)
- `caja_id` (FK NULL — seleccionada al pagar)
- `caja_movimiento_id` (FK NULL — referencia bidireccional al movimiento de caja, set al pagar)
- `fecha_pago_estimada` (DATE NULL)
- `fecha_pago_real` (DATE NULL — set al pagar)
- `observaciones` (TEXT NULL)
- `creado_por_id`, `pagado_por_id` (FK usuarios)
- `created_at`, `updated_at`, `paid_at` (timestamps)

#### Scenario: Crear OP específica con un único pedido

- GIVEN un pedido aprobado con `id=42`, `monto=10000`, `proveedor_id=7`, `moneda='ARS'`
- WHEN un usuario con `gestionar_ordenes_compra` invoca `POST /api/administracion/compras/ordenes-pago` con `{proveedor_id: 7, modo_imputacion: 'especifica', items: [{pedido_compra_id: 42, monto: 10000}]}`
- THEN se crea una OP con `estado='pendiente'`, `monto_total=10000`, `numero='OP-01-2026-00042'`
- AND se crea una imputación `(orden_pago=OP.id, pedido_compra=42)` con `monto_imputado=10000` (ver `imputaciones`)

### Requirement: REQ-OP-002 — Modos de imputación

**Priority:** must
**Type:** functional

La OP MUST soportar tres modos:

1. **`especifica`**: la OP se arma seleccionando uno o más pedidos/facturas concretos. La suma de imputaciones MUST ser igual a `monto_total`. Cualquier diferencia SHALL responder HTTP 400.
2. **`a_cuenta`**: la OP se crea sin items. Genera un crédito a cuenta del proveedor. Su `monto_total` entra como **haber** en el libro mayor al pagarse, con `destino_tipo='saldo'`.
3. **`mixta`**: combinación. La OP tiene imputaciones específicas cuya suma es **menor** que `monto_total`; el remanente queda como saldo a cuenta. Ejemplo: OP de $15.000 imputa $10.000 a pedido A + $3.000 a factura ERP B + $2.000 queda como `(orden_pago, saldo)`.

#### Scenario: OP específica con monto incorrecto

- GIVEN una OP en creación con `monto_total=10000` y un único item `pedido_compra_id=42, monto=9500`
- WHEN se envía `POST /api/administracion/compras/ordenes-pago`
- THEN el sistema MUST responder HTTP 400 con `"modo=especifica requiere que la suma de items sea igual al monto_total"`

#### Scenario: OP mixta con remanente a saldo

- GIVEN una OP con `modo_imputacion='mixta'`, `monto_total=15000`, items `[{pedido_compra_id: 10, monto: 10000}, {factura_erp_id: 'FA-001', monto: 3000}]`
- WHEN se crea la OP
- THEN la suma de items (13000) es menor que monto_total (15000)
- AND el sistema MUST generar automáticamente una tercera imputación `(orden_pago=OP.id, saldo, monto_imputado=2000)` al pagarse
- AND al pagarse, el libro mayor registra dos haberes: uno por 13000 imputado a pedidos/facturas y otro por 2000 como saldo a cuenta

### Requirement: REQ-OP-003 — Transición `pendiente` → `pagado` requiere permiso crítico

**Priority:** must
**Type:** security

El sistema MUST exigir el permiso `administracion.ejecutar_pagos` (NUEVO, `es_critico=true`) para disparar la transición `pendiente → pagado`. Sin este permiso, `POST /api/administracion/compras/ordenes-pago/{id}/pagar` SHALL responder HTTP 403.

El permiso MUST crearse en la migración inicial y NO SHALL asignarse a ningún rol por default (mismo criterio que `aprobar_ordenes_compra`).

#### Scenario: Usuario sin permiso no puede pagar

- GIVEN un usuario con `gestionar_ordenes_compra` pero SIN `ejecutar_pagos`
- WHEN invoca `POST /ordenes-pago/{id}/pagar`
- THEN el sistema MUST responder HTTP 403
- AND la OP MUST permanecer en `pendiente`

### Requirement: REQ-OP-004 — Pago atómico integra Cajas + CC proveedor

**Priority:** must
**Type:** integration

Al pasar una OP de `pendiente` a `pagado`, el sistema MUST ejecutar en **una única transacción DB** los siguientes efectos (detalle contractual en `cajas-op-integracion` y `cc-proveedor-mayor`):

1. `CajaMovimiento` con `tipo='egreso'`, `caja_id=OP.caja_id`, `monto=OP.monto_total`, `moneda=OP.moneda`.
2. `CajaDocumento` con `entidad_tipo='orden_pago'`, `entidad_id=OP.id`.
3. `CajaDocumentoMovimiento` linkeando el `CajaDocumento` al `CajaMovimiento`.
4. `ordenes_pago.caja_movimiento_id` set al `CajaMovimiento.id` creado (bidireccional).
5. Uno o más `cc_proveedor_movimientos` con `haber` según las imputaciones y el `destino_tipo` de cada una.
6. `ordenes_pago.estado='pagado'`, `fecha_pago_real=CURRENT_DATE`, `paid_at=now()`, `pagado_por_id`.

Si cualquiera de los 6 pasos falla, la transacción MUST hacer rollback completo. El sistema MUST NOT permitir estados intermedios donde la caja tenga el egreso pero la CC proveedor no esté actualizada.

#### Scenario: Pago atómico exitoso

- GIVEN una OP pendiente con `monto_total=10000`, `caja_id=5`, imputación a `pedido_compra_id=42`
- WHEN un usuario con `ejecutar_pagos` invoca `POST /ordenes-pago/{id}/pagar` con `{caja_id: 5, tipo_cambio: null, fecha_pago_real: '2026-04-17'}`
- THEN la OP pasa a `pagado`
- AND se crea exactamente 1 `CajaMovimiento` egreso de 10000 en caja 5
- AND se crea 1 `CajaDocumento` con `entidad_tipo='orden_pago'`, `entidad_id=OP.id`
- AND se crea 1 `cc_proveedor_movimientos` con `haber=10000`, `destino_tipo='pedido_compra'`, `destino_id=42`
- AND `pedidos_compra.estado=42` transiciona a `pagado`

#### Scenario: Fallo en Cajas hace rollback completo

- GIVEN una OP pendiente y una caja con saldo insuficiente (o validación de Caja que falle)
- WHEN se invoca `/pagar`
- THEN la transacción MUST abortar con rollback
- AND la OP MUST permanecer en `pendiente`
- AND NO SHALL quedar ningún `CajaMovimiento`, `CajaDocumento` ni movimiento en `cc_proveedor_movimientos`

### Requirement: REQ-OP-005 — Prevención de doble-contabilización pricing-app vs ERP directo (Observación 3)

**Priority:** must
**Type:** functional

El ERP ya registra OPs directamente (sd_id=106). Si un usuario carga un pago EN EL ERP **y ADEMÁS** lo carga como OP en pricing-app, el libro mayor recibe el haber duplicado. El sistema MUST mitigar esto con dos mecanismos:

1. **UI**: la pantalla de creación de OP MUST mostrar una advertencia visible y persistente con el texto:
   > "⚠ Si este pago ya se registró directamente en el ERP, NO lo cargues acá. Vas a duplicar el haber en la cuenta corriente del proveedor. Elegí UN solo canal por operación."

2. **Detección de posibles duplicados**: al crear una OP que imputa a una factura ERP con `numero_factura=Y` para `proveedor_id=X`, el sistema MUST consultar si existe en `tb_commercial_transactions` un documento con `(supp_id=X, ct_docnumber=Y)` cuyo `sd_id` clasifique como `ORDEN_PAGO` (ver `sale-document-catalog`). Si existe, el sistema SHALL responder HTTP 409 con `"Posible duplicado: el ERP ya registró una orden de pago para la factura {Y} del proveedor {X} (ct_transaction={id})"` y el request SHALL incluir un flag `confirmar_duplicado=true` para forzar la creación si el usuario lo asume conscientemente.

3. **Guía de usuario**: la documentación del módulo (`README-compras.md`) MUST documentar explícitamente: "Regla de oro: UN solo canal por operación. Si registrás la OP en pricing-app, NO la cargues en el ERP. Si la cargás en el ERP, NO la cargues acá."

#### Scenario: Advertencia visible en UI

- GIVEN un usuario abre el formulario "Nueva orden de pago"
- WHEN se renderiza el modal
- THEN MUST aparecer un banner de advertencia con el texto de (1) arriba
- AND el banner NO SHALL poder ocultarse/dismissarse

#### Scenario: Detección de posible duplicado

- GIVEN existe en el ERP una ct con `sd_id=106`, `supp_id=7`, `ct_docnumber='FA-00012345'`
- WHEN un usuario intenta crear una OP en pricing-app para `proveedor_id=7` imputando a factura ERP `numero_factura='FA-00012345'`
- THEN el sistema MUST responder HTTP 409 con el mensaje del punto 2 arriba
- AND la OP NO SHALL crearse

#### Scenario: Confirmación explícita fuerza creación

- GIVEN el caso anterior
- WHEN el usuario re-envía el request con `confirmar_duplicado=true` y `motivo='el ERP registró mal, esta es la correcta'`
- THEN el sistema MUST crear la OP
- AND MUST insertar un evento de auditoría en una tabla `ordenes_pago_eventos` (o reusar `pedido_compra_eventos` con `payload={motivo, ct_id_duplicada}`) con `tipo='creada_sobre_posible_duplicado'`

### Requirement: REQ-OP-006 — Anulación de OP

**Priority:** should
**Type:** functional

El sistema SHOULD permitir anular una OP que ya está en `pagado` mediante la transición `pagado → anulado`. La anulación MUST:

1. Crear un `CajaMovimiento` tipo `ingreso` por el mismo monto en la misma caja (reversa del egreso).
2. Crear `cc_proveedor_movimientos` de reverso con `debe` igual al haber original.
3. Dejar las imputaciones intactas pero marcar `ordenes_pago.estado='anulado'`.
4. Registrar evento de auditoría con `tipo='anulada'` y `payload={motivo}`.
5. Revertir el estado de los pedidos afectados (si un pedido había transicionado a `pagado` por esta OP, vuelve a `aprobado` o `pagado_parcial` según corresponda).

Requiere permiso `ejecutar_pagos` + `es_critico=true`. v1 puede dejar este endpoint como `should` (no bloqueante para launch) y formalizarse en el siguiente milestone si se prioriza.

#### Scenario: Anulación revierte caja y CC

- GIVEN una OP pagada con `monto_total=10000`, imputada a `pedido_compra_id=42`
- WHEN se invoca `POST /ordenes-pago/{id}/anular` con `motivo='pago duplicado detectado'`
- THEN se crea un ingreso en caja de 10000
- AND se crea un movimiento debe de 10000 en `cc_proveedor_movimientos`
- AND el pedido 42 vuelve a `aprobado`
- AND la OP queda en `estado='anulado'`

## OPEN QUESTIONS

- OPEN_QUESTION-OP-01: ¿La tabla `ordenes_pago_eventos` debe ser independiente o reusamos `pedido_compra_eventos` con una columna polimórfica `entidad_tipo`? Decisión de diseño (`sdd-design`). Recomendación: tabla independiente por simplicidad y para permitir índices específicos.
- OPEN_QUESTION-OP-02: ¿Se valida que `OP.moneda == pedido.moneda` para cada imputación? Si una OP ARS imputa a un pedido USD, hay conversión implícita. Respuesta técnica esperada: prohibir cross-moneda en v1, exigir OP.moneda == destino.moneda excepto en `destino_tipo='saldo'`.
