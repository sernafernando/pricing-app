# Spec Delta — Pedidos de Compra

**Change:** modulo-compras
**Capability:** pedidos-compra
**Status:** draft

## Purpose

Gestión del ciclo de vida de los pedidos de compra: alta por el PM, aprobación por un usuario con permiso crítico, auditoría inmutable de eventos y transiciones de estado controladas. Es el punto de entrada del circuito de compras; alimenta órdenes de pago y el libro mayor de CC proveedor.

## ADDED Requirements

### Requirement: REQ-PED-001 — Modelo `pedidos_compra` con máquina de estados

**Priority:** must
**Type:** functional

El sistema MUST implementar un modelo `pedidos_compra` cuyo campo `estado` SHALL tomar uno de exactamente siete valores: `borrador`, `pendiente_aprobacion`, `aprobado`, `rechazado`, `cancelado`, `pagado_parcial`, `pagado`.

El modelo MUST incluir los siguientes campos:
- `id` (PK)
- `numero` (VARCHAR, único por `(tipo='pedido', empresa_id, año)`, formato `P-01-2026-00001` — ver `numeracion-correlativa`)
- `empresa_id` (FK NOT NULL)
- `proveedor_id` (FK NOT NULL)
- `moneda` (VARCHAR NOT NULL, `ARS` | `USD`)
- `monto` (NUMERIC NOT NULL)
- `fecha_pago_texto` (VARCHAR NULL — texto libre del PM, ej. "15 días hábiles")
- `fecha_pago_estimada` (DATE NULL — completada en aprobación/pago)
- `requiere_envio` (BOOLEAN NOT NULL DEFAULT false)
- `numero_factura` (VARCHAR NULL — para matching con ERP, ver `erp-matching`)
- `estado` (VARCHAR NOT NULL DEFAULT `borrador`)
- `creado_por_id` (FK usuarios)
- `aprobado_por_id` (FK usuarios NULL)
- `created_at`, `updated_at` (timestamps)

#### Scenario: Crear un pedido arranca en borrador

- GIVEN un usuario con permiso `administracion.gestionar_ordenes_compra`
- WHEN invoca `POST /api/administracion/compras/pedidos` con `proveedor_id`, `empresa_id`, `monto`, `moneda`
- THEN se crea un pedido con `estado='borrador'`
- AND se asigna un `numero` correlativo del contador `(pedido, empresa_id, año_actual)`
- AND se inserta un evento `pedido_compra_eventos` con `tipo='creado'`, `usuario_id=creado_por_id`

#### Scenario: Un pedido cargado sin permiso falla

- GIVEN un usuario con `administracion.ver_ordenes_compra` pero SIN `administracion.gestionar_ordenes_compra`
- WHEN invoca `POST /api/administracion/compras/pedidos`
- THEN el endpoint MUST responder HTTP 403
- AND NO SHALL crearse ninguna fila en `pedidos_compra`

### Requirement: REQ-PED-002 — Transiciones de estado válidas

**Priority:** must
**Type:** functional

El sistema MUST permitir EXCLUSIVAMENTE las siguientes transiciones. Cualquier otra transición SHALL ser rechazada con HTTP 400 y mensaje `"Transición no permitida: {origen} -> {destino}"`.

Transiciones permitidas:
- `borrador` → `pendiente_aprobacion` (acción: "enviar a aprobación")
- `borrador` → `cancelado` (acción: "cancelar")
- `pendiente_aprobacion` → `aprobado` (acción: "aprobar", requiere permiso crítico)
- `pendiente_aprobacion` → `rechazado` (acción: "rechazar")
- `rechazado` → `borrador` (acción: "reabrir")
- `rechazado` → `cancelado` (acción: "cancelar definitivamente")
- `aprobado` → `pagado_parcial` (automática al crear primera imputación parcial desde una OP)
- `aprobado` → `pagado` (automática cuando la suma de imputaciones iguala el monto)
- `pagado_parcial` → `pagado` (automática)
- `aprobado` → `cancelado` (acción: "cancelar pedido aprobado", requiere reverso en CC)

Transiciones explícitamente PROHIBIDAS: cualquier salida desde `pagado`, `cancelado` (terminales); cualquier salto directo de `borrador` a `aprobado`.

#### Scenario: Aprobación requiere permiso crítico

- GIVEN un pedido en `estado='pendiente_aprobacion'`
- AND un usuario SIN `administracion.aprobar_ordenes_compra`
- WHEN invoca `POST /api/administracion/compras/pedidos/{id}/aprobar`
- THEN el sistema MUST responder HTTP 403

#### Scenario: Salto ilegal de estado es rechazado

- GIVEN un pedido en `estado='borrador'`
- WHEN el backend recibe un request para pasarlo a `aprobado` directamente
- THEN el sistema MUST responder HTTP 400 con `"Transición no permitida: borrador -> aprobado"`
- AND el pedido MUST permanecer en `borrador`

#### Scenario: Transición automática a pagado_parcial

- GIVEN un pedido aprobado con `monto=10000`
- WHEN una OP crea una imputación `(orden_pago, pedido_compra)` por `monto_imputado=4000`
- THEN el pedido MUST transicionar automáticamente a `pagado_parcial`
- AND se inserta un evento con `tipo='pago_parcial_aplicado'`, payload `{imputacion_id, monto_imputado: 4000}`

#### Scenario: Transición automática a pagado cuando se completa el monto

- GIVEN un pedido en `pagado_parcial` con `monto=10000` e imputaciones acumuladas por `6000`
- WHEN se crea una imputación adicional por `4000`
- THEN el pedido MUST transicionar a `estado='pagado'`
- AND se inserta evento `tipo='pago_completado'`

### Requirement: REQ-PED-003 — Rechazo con dos caminos explícitos

**Priority:** must
**Type:** functional

Cuando el aprobador rechaza un pedido en `pendiente_aprobacion`, el sistema MUST requerir que el aprobador elija UNO de dos caminos:

1. `rechazado` (temporal): el PM puede editarlo y reabrirlo a `borrador`.
2. Directo a `cancelado`: el aprobador marca que el pedido no debe re-enviarse.

El endpoint `POST /api/administracion/compras/pedidos/{id}/rechazar` MUST aceptar el campo `accion ∈ {'devolver_a_borrador', 'cancelar_definitivo'}`. La ausencia de este campo SHALL responder HTTP 400.

#### Scenario: Rechazo devolvible

- GIVEN un pedido en `pendiente_aprobacion`
- WHEN el aprobador envía `POST /rechazar` con `accion='devolver_a_borrador'` y `motivo='precio alto'`
- THEN el pedido MUST transicionar a `rechazado`
- AND el evento registrado SHALL tener `payload={'accion': 'devolver_a_borrador', 'motivo': 'precio alto'}`
- AND el PM puede invocar `POST /reabrir` para volverlo a `borrador`

#### Scenario: Cancelación definitiva

- GIVEN un pedido en `pendiente_aprobacion`
- WHEN el aprobador envía `POST /rechazar` con `accion='cancelar_definitivo'`
- THEN el pedido MUST transicionar a `cancelado`
- AND NO SHALL ser posible reabrirlo (el endpoint `/reabrir` SHALL responder HTTP 400)

### Requirement: REQ-PED-004 — Auditoría inmutable en `pedido_compra_eventos`

**Priority:** must
**Type:** functional

El sistema MUST mantener una tabla `pedido_compra_eventos` con las siguientes columnas:
- `id` (PK)
- `pedido_compra_id` (FK NOT NULL)
- `tipo` (VARCHAR NOT NULL — `creado`, `enviado_aprobacion`, `aprobado`, `rechazado`, `reabierto`, `cancelado`, `pago_parcial_aplicado`, `pago_completado`, `reverso_cancelacion`, `editado`)
- `usuario_id` (FK NOT NULL)
- `payload` (JSONB NULL — datos relevantes del evento: monto, motivo, imputacion_id, etc.)
- `created_at` (TIMESTAMP NOT NULL DEFAULT now())

La tabla MUST ser **append-only**. El sistema MUST NOT exponer endpoints UPDATE o DELETE sobre esta tabla. Toda acción sobre el pedido que cambie estado SHALL insertar al menos un evento en la misma transacción.

#### Scenario: Aprobación registra evento

- GIVEN un pedido en `pendiente_aprobacion`
- WHEN un usuario con permiso crítico lo aprueba
- THEN se inserta en la misma transacción un evento con `tipo='aprobado'`, `usuario_id=<aprobador>`, `payload={'fecha_pago_estimada': '2026-05-02'}`
- AND si la transacción falla, ni el cambio de estado ni el evento SHALL persistir

#### Scenario: No existe endpoint de edición de eventos

- GIVEN un evento con `id=42`
- WHEN se intenta `PUT /api/administracion/compras/pedidos/eventos/42`
- THEN el sistema MUST responder HTTP 405 (Method Not Allowed) o 404
- AND la fila en DB SHALL permanecer idéntica

### Requirement: REQ-PED-005 — Permisos diferenciados

**Priority:** must
**Type:** security

El sistema MUST enforzar los siguientes permisos:

| Acción | Permiso requerido |
|--------|-------------------|
| Listar pedidos | `administracion.ver_ordenes_compra` (155) |
| Ver detalle | `administracion.ver_ordenes_compra` (155) |
| Crear pedido | `administracion.gestionar_ordenes_compra` (156) |
| Editar pedido en borrador | `administracion.gestionar_ordenes_compra` (156) |
| Enviar a aprobación | `administracion.gestionar_ordenes_compra` (156) |
| Aprobar | `administracion.aprobar_ordenes_compra` (NUEVO, `es_critico=true`) |
| Rechazar | `administracion.aprobar_ordenes_compra` (NUEVO, `es_critico=true`) |
| Cancelar pedido aprobado | `administracion.aprobar_ordenes_compra` (NUEVO) |

El permiso `administracion.aprobar_ordenes_compra` MUST crearse en la migración inicial con `es_critico=true` y NO SHALL asignarse a ningún rol por default.

#### Scenario: Autoaprobación está permitida si tiene permiso

- GIVEN un usuario U con `gestionar_ordenes_compra` Y `aprobar_ordenes_compra`
- WHEN U crea un pedido y luego lo aprueba a sí mismo
- THEN el sistema MUST permitirlo
- AND registrar ambos eventos con `usuario_id=U.id` (v1 no bloquea auto-aprobación; es responsabilidad organizacional decidir a quién otorgar ambos permisos)

### Requirement: REQ-PED-006 — Edición restringida a `borrador`

**Priority:** must
**Type:** functional

El sistema MUST permitir la edición de campos (`monto`, `moneda`, `fecha_pago_texto`, `requiere_envio`, `numero_factura`) SOLAMENTE cuando `estado='borrador'`. En cualquier otro estado, `PUT /api/administracion/compras/pedidos/{id}` SHALL responder HTTP 409 con `"No se puede editar un pedido en estado {estado}"`.

Excepción: el campo `numero_factura` MAY ser editable también en `estado='aprobado'` o `pagado_parcial` (para completarlo cuando el PM recibe la factura del proveedor), y tal edición SHALL registrar un evento con `tipo='editado'` y `payload={'campo': 'numero_factura', 'valor_anterior': ..., 'valor_nuevo': ...}`.

#### Scenario: Edición de borrador OK

- GIVEN un pedido en `borrador` con `monto=5000`
- WHEN el creador lo edita a `monto=5500`
- THEN el update SHALL persistir
- AND se inserta evento `tipo='editado'` con payload del diff

#### Scenario: Edición de pedido aprobado rechazada

- GIVEN un pedido en `aprobado`
- WHEN se intenta `PUT` cambiando `monto`
- THEN el sistema MUST responder HTTP 409
- AND la fila SHALL permanecer intacta

#### Scenario: numero_factura editable en aprobado

- GIVEN un pedido en `aprobado` con `numero_factura=NULL`
- WHEN el PM lo edita agregando `numero_factura='A-00012345'`
- THEN el update SHALL persistir
- AND se dispara el matching bidireccional con ERP (ver `erp-matching` REQ-ERP-004)

## OPEN QUESTIONS

- OPEN_QUESTION-PED-01: ¿Se permite adjuntar archivos (remito escaneado, confirmación del proveedor) al pedido en v1? **Respuesta del proposal**: no, los adjuntos quedan para v2 usando `CajaDocumento` polimórfico. Se documenta aquí para cerrar el tema en diseño.
- OPEN_QUESTION-PED-02: ¿Se permite reasignar `creado_por_id` si el PM original deja la empresa? No está contemplado en v1; mantener el `creado_por_id` histórico y que el reemplazo actúe como editor.
