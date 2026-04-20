# Spec Delta — Imputaciones

**Change:** modulo-compras
**Capability:** imputaciones
**Status:** draft

## Purpose

Tabla unificada que relaciona un **origen de crédito** (OP o NC del ERP) con un **destino de deuda** (pedido, factura ERP o saldo a cuenta). Con `origen_tipo` / `destino_tipo` abiertos a VARCHAR para permitir extensión v2 sin migración destructiva, con whitelist de combinaciones válidas a nivel servicio.

## ADDED Requirements

### Requirement: REQ-IMP-001 — Modelo `imputaciones` unificado

**Priority:** must
**Type:** functional

El sistema MUST implementar el modelo `imputaciones` con los siguientes campos:
- `id` (PK)
- `origen_tipo` (VARCHAR NOT NULL — ABIERTO, no ENUM)
- `origen_id` (INTEGER NOT NULL — id de la entidad origen según `origen_tipo`)
- `destino_tipo` (VARCHAR NOT NULL — ABIERTO)
- `destino_id` (INTEGER NULL — NULL solo si `destino_tipo='saldo'`)
- `monto_imputado` (NUMERIC NOT NULL, > 0)
- `moneda_imputada` (VARCHAR NOT NULL — debe coincidir con moneda del origen y del destino)
- `tipo_cambio` (NUMERIC NULL — solo relevante si origen y destino son USD/ARS y hay conversión)
- `proveedor_id` (FK NOT NULL — redundante pero crítico para queries de CC; SHALL validarse consistente con origen y destino)
- `creado_por_id` (FK usuarios)
- `created_at` (TIMESTAMP)
- `reimputada_desde_id` (FK self NULL — si esta es una reimputación, apunta a la imputación original)

Índices:
- `(proveedor_id, created_at DESC)` para queries de CC
- `(origen_tipo, origen_id)` y `(destino_tipo, destino_id)`

#### Scenario: Crear imputación `(orden_pago, pedido_compra)`

- GIVEN una OP con `id=100`, `proveedor_id=7`, `moneda='ARS'`
- AND un pedido con `id=42`, `proveedor_id=7`, `moneda='ARS'`, `estado='aprobado'`
- WHEN el backend crea una imputación al pagarse la OP
- THEN se inserta `{origen_tipo: 'orden_pago', origen_id: 100, destino_tipo: 'pedido_compra', destino_id: 42, monto_imputado: 10000, moneda_imputada: 'ARS', proveedor_id: 7}`

### Requirement: REQ-IMP-002 — Whitelist de combinaciones válidas v1

**Priority:** must
**Type:** functional

El sistema MUST mantener en `backend/app/services/imputaciones_service.py` una constante:

```python
COMBOS_VALIDOS_V1 = {
    ('orden_pago', 'pedido_compra'),
    ('orden_pago', 'factura_erp'),
    ('orden_pago', 'saldo'),
    ('nota_credito_erp', 'pedido_compra'),
    ('nota_credito_erp', 'factura_erp'),
    ('nota_credito_erp', 'saldo'),
}
```

Cualquier intento de crear una imputación cuyo `(origen_tipo, destino_tipo)` NO esté en `COMBOS_VALIDOS_V1` SHALL responder HTTP 400 con el mensaje **exacto**: `"Combinación origen/destino no soportada en v1"`. La validación MUST correr antes de cualquier escritura en DB.

#### Scenario: Combo válido OK

- GIVEN un request con `origen_tipo='orden_pago'`, `destino_tipo='factura_erp'`
- WHEN se invoca la creación de la imputación
- THEN el sistema SHALL proceder (sin rechazo por whitelist)

#### Scenario: Combo inválido rechazado

- GIVEN un request con `origen_tipo='nota_credito_local'`, `destino_tipo='pedido_compra'`
- WHEN se intenta crear la imputación
- THEN el sistema MUST responder HTTP 400 con `"Combinación origen/destino no soportada en v1"`
- AND NO SHALL escribir en `imputaciones`

#### Scenario: Extensión v2 no requiere migración

- GIVEN se decide agregar en v2 `nota_credito_local` como origen
- WHEN se actualiza la constante `COMBOS_VALIDOS_V1` (o se renombra a `COMBOS_VALIDOS_V2`)
- THEN NO SHALL requerirse ninguna migración de schema (columnas siguen siendo VARCHAR abiertas)

### Requirement: REQ-IMP-003 — Validación de consistencia proveedor + moneda

**Priority:** must
**Type:** functional

El sistema MUST validar previo a insertar:

1. `proveedor_id` de la imputación == `proveedor_id` del origen == `proveedor_id` del destino (cuando `destino_tipo != 'saldo'`).
2. `moneda_imputada` == moneda del origen == moneda del destino.
3. `monto_imputado > 0` (sin imputaciones negativas; la reversa se modela como imputación independiente con `origen_tipo='nota_credito_erp'` o como movimiento de ajuste directo en CC).

Violación de cualquier regla SHALL responder HTTP 400 con mensaje específico.

#### Scenario: Proveedor inconsistente

- GIVEN OP con `proveedor_id=7` y pedido con `proveedor_id=8`
- WHEN se intenta imputar OP a ese pedido
- THEN el sistema MUST responder HTTP 400 con `"Proveedor inconsistente entre origen y destino"`

#### Scenario: Moneda inconsistente

- GIVEN OP con `moneda='USD'` y pedido con `moneda='ARS'`
- WHEN se intenta imputar
- THEN el sistema MUST responder HTTP 400 con `"Moneda inconsistente entre origen y destino"` (v1 prohíbe cross-moneda salvo `destino_tipo='saldo'`)

### Requirement: REQ-IMP-004 — Distribución automática FIFO

**Priority:** must
**Type:** functional

El sistema MUST exponer el endpoint `POST /api/administracion/compras/ordenes-pago/{op_id}/distribuir-automatico` que:

1. Lista las "deudas pendientes" del proveedor en orden FIFO por `created_at ASC`. La lista incluye:
   - Pedidos en `aprobado` o `pagado_parcial` con saldo pendiente (monto - imputado_acumulado).
   - Facturas ERP vigentes (de la vista `v_facturas_compra_vigentes`, ver `erp-matching`) con saldo pendiente.
2. Aplica el `monto_total` restante de la OP a cada deuda en orden, creando imputaciones. Si una deuda queda cubierta parcialmente, la siguiente recibe el remanente.
3. Si sobra monto tras cubrir todas las deudas, crea una imputación `(orden_pago, saldo)` con el remanente.
4. Todo en una única transacción. Si cualquier validación falla, rollback completo.

El endpoint MUST retornar un resumen con la lista de imputaciones creadas: `[{destino_tipo, destino_id, monto_imputado}, ...]`.

#### Scenario: FIFO con cobertura completa

- GIVEN una OP con `monto_total=15000`, `modo_imputacion='a_cuenta'` (o `mixta` con items previos ya imputando parcialmente), proveedor 7, moneda ARS
- AND deudas pendientes del proveedor 7 ordenadas por FIFO: pedido P1 saldo=5000 (2026-01-10), pedido P2 saldo=7000 (2026-02-15), factura ERP F3 saldo=10000 (2026-03-05)
- AND el remanente de la OP es 15000 (supongamos sin items previos)
- WHEN se invoca `/distribuir-automatico`
- THEN se crean 3 imputaciones: `(OP, P1, 5000)`, `(OP, P2, 7000)`, `(OP, F3, 3000)`
- AND NO SHALL haber imputación a `saldo` (monto consumido exactamente)
- AND P1 transiciona a `pagado`, P2 transiciona a `pagado`, F3 sigue con saldo pendiente `10000-3000=7000`

#### Scenario: FIFO con remanente a saldo

- GIVEN una OP con `monto_total=20000` y deudas totales pendientes del proveedor = 13000
- WHEN se invoca `/distribuir-automatico`
- THEN se crean N imputaciones cubriendo cada deuda
- AND se crea 1 imputación adicional `(OP, saldo, 7000)` con el remanente

#### Scenario: Sin deudas, todo a saldo

- GIVEN una OP de 5000 y el proveedor no tiene deudas pendientes
- WHEN se invoca `/distribuir-automatico`
- THEN se crea UNA sola imputación `(OP, saldo, 5000)`
- AND el libro mayor refleja el haber con `destino_tipo='saldo'`

### Requirement: REQ-IMP-005 — Re-imputación diferida

**Priority:** must
**Type:** functional

El sistema MUST permitir "mover" una imputación ya aplicada de un destino a otro SIN anular la OP ni el pago. Se modela como:

1. Inserción de una nueva fila en `imputaciones` con `origen_tipo='reimputacion'` (nuevo origen_tipo, agregar a `COMBOS_VALIDOS_V1`), `origen_id=imputacion_original.id`, `destino_tipo=<nuevo>`, `destino_id=<nuevo>`, `monto_imputado=<monto>`, `reimputada_desde_id=imputacion_original.id`.
2. Marcar la imputación original con un campo o flag (alternativa: insertar un movimiento de ajuste en `cc_proveedor_movimientos` que reverse el destino original y aplique el nuevo).

**Decisión recomendada en diseño**: agregar a la whitelist el combo `('reimputacion', 'pedido_compra')`, `('reimputacion', 'factura_erp')`, `('reimputacion', 'saldo')`. La reimputación genera DOS movimientos en `cc_proveedor_movimientos`: un `debe` que cancela el destino anterior + un `haber` que aplica al destino nuevo, dejando el total del proveedor igual.

Endpoint: `POST /api/administracion/compras/imputaciones/{id}/reimputar` con body `{destino_tipo, destino_id}`. Requiere permiso `ejecutar_pagos`.

#### Scenario: Reimputar de pedido a factura ERP

- GIVEN una imputación `IM1` con `(orden_pago=100, pedido_compra=42, monto_imputado=5000)`
- AND luego aparece en el ERP la factura real `FA-00012345` que corresponde al pedido 42
- WHEN se invoca `POST /imputaciones/IM1/reimputar` con `{destino_tipo: 'factura_erp', destino_id: 'FA-00012345'}`
- THEN se crea `IM2` con `origen_tipo='reimputacion', origen_id=IM1.id, destino_tipo='factura_erp', destino_id='FA-00012345', monto_imputado=5000`
- AND el libro mayor registra: debe de 5000 contra pedido 42 (reversa) + haber de 5000 contra factura FA-00012345
- AND el saldo total del proveedor NO cambia
- AND el pedido 42 vuelve a su estado previo (de `pagado`/`pagado_parcial` a `aprobado` si la imputación era la única)

#### Scenario: Usuario sin permiso no puede reimputar

- GIVEN un usuario sin `ejecutar_pagos`
- WHEN invoca `POST /imputaciones/{id}/reimputar`
- THEN el sistema MUST responder HTTP 403

### Requirement: REQ-IMP-006 — Imputaciones generan movimiento en CC proveedor

**Priority:** must
**Type:** integration

Cada vez que se persiste una fila en `imputaciones`, el sistema MUST insertar en la **misma transacción** las filas correspondientes en `cc_proveedor_movimientos` (ver `cc-proveedor-mayor` REQ-CC-002). El servicio `imputaciones_service.py` MUST invocar al servicio `cc_proveedor_service.aplicar_imputacion(imp)` dentro del mismo contexto transaccional.

#### Scenario: Creación atómica

- WHEN se crea una imputación `(orden_pago, pedido_compra, 5000, ARS)` para `proveedor_id=7`
- THEN en la misma transacción se inserta `cc_proveedor_movimientos` con `tipo='haber', origen='imputacion', origen_id=imp.id, monto=5000, moneda='ARS', proveedor_id=7`
- AND si falla el insert en `cc_proveedor_movimientos`, la imputación NO SHALL persistir

## OPEN QUESTIONS

- OPEN_QUESTION-IMP-01: Para `destino_tipo='factura_erp'`, ¿`destino_id` guarda `ct_transaction` del ERP o un id interno propio de una tabla de facturas locales? v1 = `ct_transaction` (VARCHAR o INT según schema ERP). Confirmar en diseño.
- OPEN_QUESTION-IMP-02: ¿La reimputación de una imputación ya reimputada es válida (cadena)? v1 = prohibir; si `reimputada_desde_id` no es null en la imputación original del request → HTTP 400.
