# Spec Delta — Libro Mayor de CC Proveedor

**Change:** modulo-compras
**Capability:** cc-proveedor-mayor
**Status:** draft

## Purpose

Implementar un libro mayor propio e inmutable (`cc_proveedor_movimientos`) como **fuente de verdad** del saldo por proveedor, con soporte multi-moneda (estrategia C: cada movimiento guarda su moneda original + TC). Convive en v1 con la tabla snapshot `cuentas_corrientes_proveedores` (espejo del ERP), con un job de reconciliación diaria que mide divergencias. Es el criterio objetivo para deprecar el snapshot en v2.

## ADDED Requirements

### Requirement: REQ-CC-001 — Modelo `cc_proveedor_movimientos` inmutable

**Priority:** must
**Type:** functional

El sistema MUST implementar el modelo `cc_proveedor_movimientos` con los siguientes campos:
- `id` (PK)
- `proveedor_id` (FK NOT NULL)
- `empresa_id` (FK NOT NULL)
- `fecha_movimiento` (DATE NOT NULL)
- `tipo` (VARCHAR NOT NULL — `debe` | `haber` | `ajuste`)
- `monto` (NUMERIC NOT NULL, > 0)
- `moneda` (VARCHAR NOT NULL — `ARS` | `USD`)
- `tipo_cambio_a_ars` (NUMERIC NULL — TC de ARS/USD en `fecha_movimiento` para la vista consolidada estimada)
- `origen_tipo` (VARCHAR NOT NULL — `pedido_compra`, `orden_pago`, `factura_erp`, `nota_credito_erp`, `imputacion`, `cancelacion_pedido`, `reimputacion`, `ajuste_manual`)
- `origen_id` (INTEGER NULL — id de la entidad que generó el movimiento)
- `descripcion` (VARCHAR NULL)
- `creado_por_id` (FK usuarios NULL — NULL si el movimiento lo generó un proceso automático, ej. cron ERP)
- `created_at` (TIMESTAMP NOT NULL DEFAULT now())

La tabla MUST ser **append-only**: NO SHALL exponerse endpoints UPDATE ni DELETE. La reversa de un movimiento se modela como un nuevo movimiento con `tipo` opuesto.

Índices requeridos:
- `(proveedor_id, fecha_movimiento DESC, id DESC)` para queries de CC por proveedor.
- `(origen_tipo, origen_id)` para trazabilidad reverse.
- `(empresa_id, proveedor_id)` para queries multi-empresa.

#### Scenario: Aprobación de pedido inserta debe

- GIVEN un pedido con `monto=10000`, `moneda='ARS'`, `proveedor_id=7`
- WHEN el pedido transiciona a `aprobado`
- THEN se inserta en `cc_proveedor_movimientos`: `{proveedor_id: 7, tipo: 'debe', monto: 10000, moneda: 'ARS', origen_tipo: 'pedido_compra', origen_id: pedido.id, fecha_movimiento: pedido.fecha_aprobacion}`

#### Scenario: Intentar editar un movimiento falla

- GIVEN un movimiento con `id=500`
- WHEN se invoca `PUT /api/administracion/compras/cc-proveedor/movimientos/500`
- THEN el sistema MUST responder HTTP 405 o 404 (no existe el endpoint)
- AND la fila SHALL permanecer intacta

### Requirement: REQ-CC-002 — Saldo calculado por moneda (estrategia C)

**Priority:** must
**Type:** functional

El sistema MUST calcular el saldo de un proveedor agrupado por moneda, NO como un valor consolidado único. El endpoint `GET /api/administracion/compras/cc-proveedor/{proveedor_id}` SHALL retornar:

```json
{
  "proveedor_id": 7,
  "saldos_por_moneda": [
    {"moneda": "ARS", "saldo": 15000.00},
    {"moneda": "USD", "saldo": 320.50}
  ],
  "saldo_consolidado_estimado_ars": {
    "valor": 342500.00,
    "tc_usado": 1020.00,
    "fecha_tc": "2026-04-17",
    "disclaimer": "Estimado al TC del día. Fuente de verdad: saldos_por_moneda."
  },
  "movimientos": [...]
}
```

El saldo por moneda MUST calcularse como: `SUM(CASE WHEN tipo='debe' THEN monto WHEN tipo='haber' THEN -monto ELSE signo_ajuste * monto END) GROUP BY moneda`.

El `saldo_consolidado_estimado_ars` MUST ser una vista SECUNDARIA claramente etiquetada como estimación; NO SHALL presentarse como saldo oficial.

#### Scenario: Saldo separado USD y ARS

- GIVEN un proveedor con movimientos: debe 10000 ARS, haber 5000 ARS, debe 200 USD, haber 50 USD
- WHEN se consulta el endpoint
- THEN `saldos_por_moneda` MUST retornar `[{moneda: ARS, saldo: 5000}, {moneda: USD, saldo: 150}]`

#### Scenario: UI presenta saldo por moneda como principal

- GIVEN la vista de CC en frontend
- WHEN se renderiza el drill-down del proveedor
- THEN MUST mostrar dos tarjetas grandes con "Saldo ARS: $5.000" y "Saldo USD: US$150" como datos principales
- AND MAY mostrar un badge secundario con "Estimado consolidado: $158.000 ARS @ TC 1020" claramente etiquetado como estimación

### Requirement: REQ-CC-003 — Agrupación visual por pedido en UI

**Priority:** should
**Type:** functional

El frontend SHOULD ofrecer una vista alternativa "agrupada por pedido" donde los movimientos se colapsan por `(origen_tipo='pedido_compra', origen_id)` y sus imputaciones relacionadas se muestran como filas hijas. Esta vista responde al feedback del usuario durante la revisión del proposal.

Toggle en UI: `[Cronológico] | [Agrupado por pedido]`.

#### Scenario: Vista agrupada

- GIVEN un proveedor con 2 pedidos aprobados (P1=10000, P2=5000) y 1 OP pagada imputando 8000 a P1 y 3000 a P2
- WHEN el usuario activa "Agrupado por pedido"
- THEN MUST ver dos cards:
  - Card P1: debe 10000, haber 8000, saldo 2000
  - Card P2: debe 5000, haber 3000, saldo 2000
- AND la suma de cards MUST igualar el saldo total del proveedor

### Requirement: REQ-CC-004 — Reconciliación diaria con snapshot (Observación 1)

**Priority:** must
**Type:** integration

El sistema MUST ejecutar un job cron diario (ej. 03:00 AM) que reconcilie el libro mayor propio contra la tabla snapshot `cuentas_corrientes_proveedores`. El job MUST:

1. Para cada proveedor activo con movimientos en los últimos 365 días, calcular el saldo por moneda desde `cc_proveedor_movimientos`.
2. Obtener el saldo que reporta el snapshot `cuentas_corrientes_proveedores` (si existe fila para ese proveedor).
3. Comparar ambos valores con una tolerancia de `$0.01` (redondeo de decimales).
4. Si hay divergencia, persistir en una nueva tabla `cc_reconciliacion_log` con: `fecha`, `proveedor_id`, `moneda`, `saldo_libro_mayor`, `saldo_snapshot`, `divergencia`.
5. Si alguna divergencia supera el umbral `$0.01`, emitir una **notificación admin** visible en el panel de administración con el listado de proveedores divergentes.

La tabla `cc_reconciliacion_log` MUST incluir:
- `id`, `fecha_corrida` (DATE), `proveedor_id`, `moneda`, `saldo_libro_mayor`, `saldo_snapshot`, `diferencia`, `nota` (VARCHAR NULL — explicación manual post-revisión)

#### Scenario: Sin divergencias

- GIVEN al fin del día todos los saldos de libro mayor igualan los saldos de snapshot (tolerancia $0.01)
- WHEN el cron de reconciliación corre a las 03:00
- THEN NO SHALL crearse filas con `diferencia > 0.01` en `cc_reconciliacion_log` (o se crean con `diferencia=0`)
- AND NO SHALL generarse notificación admin

#### Scenario: Divergencia detectada

- GIVEN un proveedor donde el libro mayor dice ARS 10000 y el snapshot dice ARS 9800
- WHEN el cron corre
- THEN se inserta `cc_reconciliacion_log {proveedor_id: X, moneda: 'ARS', saldo_libro_mayor: 10000, saldo_snapshot: 9800, diferencia: 200}`
- AND se crea una notificación admin "Divergencia detectada para proveedor X: ARS 200"

### Requirement: REQ-CC-005 — Criterio de deprecación del snapshot

**Priority:** must
**Type:** non-functional

El snapshot `cuentas_corrientes_proveedores` NO SHALL deprecarse en v1. El sistema MUST mantener el criterio objetivo documentado: el change de deprecación SOLO PUEDE arrancar cuando se cumplan **TODOS** los siguientes, medidos automáticamente:

1. **30 días consecutivos sin divergencias** detectadas en `cc_reconciliacion_log` (umbral: `$0.01` por proveedor/moneda).
2. Cobertura mínima del 80% de proveedores activos con al menos un movimiento en el libro mayor propio en los últimos 30 días.
3. Aprobación manual de usuario con rol admin, registrada como evento.

Sin reconciliación diaria operativa (REQ-CC-004) activa, el criterio (1) **NO SHALL poder evaluarse**, bloqueando cualquier propuesta de deprecación.

#### Scenario: Criterio no cumplido - bloqueo

- GIVEN una propuesta de deprecar el snapshot
- AND `cc_reconciliacion_log` muestra divergencias en 5 de los últimos 30 días
- WHEN se pretende ejecutar la deprecación
- THEN el sistema (o el proceso de diseño de change) MUST bloquear la acción documentando qué criterio no se cumple

#### Scenario: Métrica visible en admin

- GIVEN el panel de administración `/administracion/compras/reconciliacion`
- WHEN un admin lo abre
- THEN MUST mostrar: "Días consecutivos sin divergencia: 12 / 30 necesarios", "Cobertura de proveedores: 67% / 80% necesario", "Estado: criterio NO cumplido"

### Requirement: REQ-CC-006 — Multi-moneda: TC por movimiento

**Priority:** must
**Type:** functional

Cada fila de `cc_proveedor_movimientos` MUST persistir el tipo de cambio ARS/USD en `fecha_movimiento` en la columna `tipo_cambio_a_ars` (estrategia C del proposal). El TC se toma de la tabla existente `tipo_cambio` con el patrón `fecha <= movimiento.fecha_movimiento ORDER BY fecha DESC LIMIT 1`.

Este TC NO SHALL alterar el saldo por moneda (es solo referencia para la vista consolidada); SHALL persistirse como snapshot histórico para que el consolidado estimado sea reproducible a posteriori.

#### Scenario: TC guardado al momento del movimiento

- GIVEN un movimiento en USD del día 2026-04-17
- WHEN se inserta en `cc_proveedor_movimientos`
- THEN `tipo_cambio_a_ars` SHALL ser el último TC ≤ 2026-04-17 de la tabla `tipo_cambio`
- AND el valor queda congelado; si mañana el TC cambia, el movimiento del día 17 retiene su TC original

## OPEN QUESTIONS

- OPEN_QUESTION-CC-01: ¿Las notificaciones admin de divergencias se implementan reusando un sistema existente o se crea uno nuevo? Verificar en diseño si hay un modelo `AdminNotificacion` o similar; si no, crear uno mínimo (tabla `admin_notificaciones` con `tipo, mensaje, leida, created_at`).
- OPEN_QUESTION-CC-02: El cron de reconciliación ¿debe reusar `sync_commercial_transactions_guid.py` como hook post-sync o correr standalone? Recomendación: standalone (un cron diario a las 03:00), desacoplado del sync de ERP para poder correrlo manualmente desde admin.
