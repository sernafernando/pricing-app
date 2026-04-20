# Spec Delta — Integración Cajas ↔ Orden de Pago

**Change:** modulo-compras
**Capability:** cajas-op-integracion
**Status:** draft

## Purpose

Formalizar la integración entre el módulo de Cajas existente y las Órdenes de Pago del nuevo módulo de compras. Al pagar una OP se crea un egreso en caja + un `CajaDocumento` polimórfico, todo dentro de una transacción atómica, reusando la infraestructura existente sin modificarla estructuralmente.

## ADDED Requirements

### Requirement: REQ-CAJ-001 — Transacción atómica al marcar OP como pagada

**Priority:** must
**Type:** integration

Cuando una OP transiciona de `pendiente` → `pagado` (ver `ordenes-pago` REQ-OP-004), el sistema MUST ejecutar dentro de **una única transacción DB** los siguientes 5 pasos en este orden:

1. **Crear `CajaMovimiento`** con:
   - `tipo='egreso'`
   - `caja_id=OP.caja_id` (campo seleccionado en el form de pago)
   - `monto=OP.monto_total`
   - `moneda=OP.moneda`
   - `tipo_cambio=OP.tipo_cambio` (si aplica conversión)
   - `fecha=OP.fecha_pago_real`
   - `descripcion="OP {OP.numero} - {proveedor.nombre}"`
   - `creado_por_id=<usuario que pagó>`

2. **Crear `CajaDocumento`** con:
   - `entidad_tipo='orden_pago'`
   - `entidad_id=OP.id`
   - `tipo_documento_id=<id del tipo "Orden de Pago">` (seed previo, ver REQ-CAJ-003)
   - `numero=OP.numero` (ej. `OP-01-2026-00042`)
   - `proveedor_id=OP.proveedor_id`
   - `monto=OP.monto_total`

3. **Crear `CajaDocumentoMovimiento`** linkeando ambos:
   - `caja_documento_id=<creado en paso 2>`
   - `caja_movimiento_id=<creado en paso 1>`
   - `monto_aplicado=OP.monto_total`

4. **Actualizar `ordenes_pago`** con la referencia bidireccional:
   - `caja_movimiento_id=<id del CajaMovimiento creado>`
   - `estado='pagado'`, `fecha_pago_real`, `paid_at`, `pagado_por_id`

5. **Insertar movimientos en `cc_proveedor_movimientos`** (haber) según las imputaciones de la OP (ver `cc-proveedor-mayor` REQ-CC-002 y `imputaciones` REQ-IMP-006).

Si cualquiera de los 5 pasos falla, la transacción MUST hacer rollback total. NO SHALL quedar estado intermedio consistente parcialmente.

#### Scenario: Pago exitoso crea los 5 artefactos

- GIVEN OP pendiente con `id=50, numero='OP-01-2026-00042', monto_total=10000, moneda='ARS', proveedor_id=7`
- AND imputación a `pedido_compra_id=42` por 10000
- WHEN un usuario con `ejecutar_pagos` invoca `POST /ordenes-pago/50/pagar` con `{caja_id: 5}`
- THEN la DB SHALL contener:
  - 1 `CajaMovimiento` (tipo=egreso, caja_id=5, monto=10000)
  - 1 `CajaDocumento` (entidad_tipo='orden_pago', entidad_id=50)
  - 1 `CajaDocumentoMovimiento` linkeando ambos
  - `ordenes_pago.caja_movimiento_id` poblado
  - 1 `cc_proveedor_movimientos` (tipo=haber, destino_tipo='pedido_compra', destino_id=42, monto=10000)

#### Scenario: Rollback si falla uno de los pasos

- GIVEN una OP y una caja cuyo saldo sería negativo tras el egreso (supongamos que Cajas tiene validación de saldo mínimo configurable)
- WHEN se invoca `/pagar`
- THEN la transacción SHALL fallar en el paso 1
- AND NO SHALL crearse CajaDocumento, CajaDocumentoMovimiento ni cc_proveedor_movimientos
- AND la OP MUST permanecer en `pendiente`

### Requirement: REQ-CAJ-002 — Reuso de `caja_service.crear_movimiento` existente

**Priority:** must
**Type:** integration

El módulo de compras MUST reusar la función existente `caja_service.crear_movimiento(entidad_tipo, entidad_id, ...)` (ver línea 437 de `backend/app/services/caja_service.py` según obs #103). NO SHALL reimplementarse lógica de Cajas; la responsabilidad del módulo de compras es **invocar** el servicio con los parámetros correctos.

El contrato del servicio existente ya acepta `entidad_tipo` y `entidad_id` polimórficos — estrenamos el valor `'orden_pago'` para `entidad_tipo` sin modificar el servicio.

#### Scenario: Reuso sin modificar servicio

- GIVEN el servicio `caja_service.crear_movimiento` con la firma actual
- WHEN el `ordenes_pago_service.pagar(op)` lo invoca con `entidad_tipo='orden_pago', entidad_id=op.id, monto=op.monto_total, ...`
- THEN el servicio SHALL procesar sin modificaciones en su código
- AND el `CajaDocumento` resultante SHALL tener `entidad_tipo='orden_pago'`

### Requirement: REQ-CAJ-003 — Seed de `caja_tipo_documentos` con "Orden de Pago"

**Priority:** must
**Type:** functional

La migración inicial del módulo MUST insertar (idempotentemente) una fila en `caja_tipo_documentos` con:
- `codigo='orden_pago'`
- `nombre='Orden de Pago'`
- `descripcion='Egreso de caja por pago a proveedor generado desde módulo de compras'`
- `activo=true`

Este tipo MUST estar disponible para que `CajaDocumento.tipo_documento_id` pueda referenciarlo al crear el documento en el paso 2 de REQ-CAJ-001.

#### Scenario: Seed idempotente

- GIVEN la migración se ejecuta por primera vez
- WHEN corre el seed
- THEN se inserta la fila en `caja_tipo_documentos`
- AND si la migración se re-ejecuta (ej. en entorno de dev), SHALL detectar la fila existente y NO duplicarla (ON CONFLICT DO NOTHING o equivalente)

### Requirement: REQ-CAJ-004 — Link "Ver OP" en el frontend de Cajas

**Priority:** should
**Type:** functional

El frontend de Cajas (`AdministracionCaja.jsx` o el componente de detalle de `CajaMovimiento`) SHOULD detectar cuando `CajaDocumento.entidad_tipo='orden_pago'` y renderizar un link clickeable "Ver OP #OP-01-2026-00042" que navega a `/administracion/compras/ordenes-pago/{entidad_id}`.

Comportamiento análogo para otros `entidad_tipo` existentes (si los hay) se mantiene sin cambios.

#### Scenario: Link visible

- GIVEN un `CajaMovimiento` egreso asociado a un `CajaDocumento` con `entidad_tipo='orden_pago', entidad_id=50`
- WHEN el usuario abre el detalle del movimiento en Cajas
- THEN MUST ver un link "Ver OP #OP-01-2026-00042"
- WHEN el usuario hace click
- THEN SHALL navegar a `/administracion/compras/ordenes-pago/50`

### Requirement: REQ-CAJ-005 — Anulación de OP impacta Caja como ingreso

**Priority:** should
**Type:** integration

Cuando una OP anulada (ver `ordenes-pago` REQ-OP-006), el sistema SHALL crear en la misma transacción:
1. `CajaMovimiento` con `tipo='ingreso'`, `caja_id=<misma caja del egreso original>`, `monto=OP.monto_total`, `descripcion='Reverso OP {OP.numero} - {motivo}'`.
2. Un nuevo `CajaDocumento` (o marcar el existente como anulado; decidir en diseño) que refleje la reversa.
3. Movimientos de reverso en `cc_proveedor_movimientos` con `tipo='debe'`.

Esto mantiene la consistencia contable: todo lo que salió, vuelve a entrar cuando se anula.

#### Scenario: Anulación genera ingreso

- GIVEN una OP pagada hace 3 días, con `CajaMovimiento` egreso de 10000
- WHEN se anula con motivo `'pago duplicado detectado'`
- THEN se crea un `CajaMovimiento` ingreso de 10000 en la misma caja
- AND se crea/marca un `CajaDocumento` reflejando la reversa
- AND se insertan movimientos de `debe` en `cc_proveedor_movimientos` por el mismo monto

## OPEN QUESTIONS

- OPEN_QUESTION-CAJ-01: ¿El `CajaDocumento` se reusa (se marca como anulado) o se crea uno nuevo de reverso? Decidir en diseño según convención actual del módulo Cajas. Recomendación: crear uno nuevo con `tipo_documento='orden_pago_anulada'` o similar, para preservar trazabilidad.
- OPEN_QUESTION-CAJ-02: ¿Qué pasa si la caja elegida no tiene saldo suficiente? Depende de si el módulo Cajas valida saldo mínimo o permite negativo. Confirmar en diseño y alinear con negocio.
- OPEN_QUESTION-CAJ-03: ¿El `tipo_cambio` se aplica automáticamente cuando OP.moneda != caja.moneda? Ejemplo: OP USD pagada desde caja ARS → convertir con TC del día. Definir contrato en diseño.
