# Spec Delta — Logística / Retiro en Proveedor

**Change:** modulo-compras
**Capability:** logistica-retiro-proveedor
**Status:** draft

## Purpose

Extender la tabla existente `etiquetas_envio` (hoy exclusivamente orientada a cliente) para soportar retiros en proveedor. Cuando un pedido de compra tiene `requiere_envio=true`, el sistema genera automáticamente una etiqueta en TabEnviosFlex reusando la dirección del proveedor. Backward-compatible: todas las columnas nuevas son nullable y las filas existentes se backfillean con `tipo_envio='cliente'`.

## MODIFIED Requirements

### Requirement: REQ-LOG-001 — Extensión de `etiquetas_envio` con tipo y proveedor

**Priority:** must
**Type:** functional

La tabla existente `etiquetas_envio` MUST extenderse con las siguientes columnas (todas nullable excepto `tipo_envio`):

- `tipo_envio` (VARCHAR NOT NULL DEFAULT `'cliente'`) — valores: `'cliente'` | `'retiro_proveedor'`. Si v2 aparecen más tipos (ej. `'transferencia_entre_sucursales'`), SHALL agregarse a este ENUM/check.
- `proveedor_id` (FK NULL) — set cuando `tipo_envio='retiro_proveedor'`.
- `proveedor_direccion_id` (FK NULL) — dirección concreta del proveedor usada como origen del retiro.
- `pedido_compra_id` (FK NULL) — pedido que generó la etiqueta.

Invariantes:
- SI `tipo_envio='cliente'` → `proveedor_id`, `proveedor_direccion_id`, `pedido_compra_id` SHALL ser NULL.
- SI `tipo_envio='retiro_proveedor'` → `proveedor_id` y `pedido_compra_id` SHALL ser NOT NULL (validar por servicio y check constraint opcional).

(Previously: la tabla asumía `cliente_id NOT NULL` implícitamente en toda lógica de TabEnviosFlex; el cambio agrega la columna `tipo_envio` para discriminar.)

#### Scenario: Migración con backfill

- GIVEN `etiquetas_envio` tiene 2500 filas existentes al momento del deploy
- WHEN se ejecuta la migración Alembic
- THEN todas las filas existentes SHALL actualizar `tipo_envio='cliente'` (backfill)
- AND `proveedor_id`, `proveedor_direccion_id`, `pedido_compra_id` SHALL quedar NULL en todas ellas
- AND las queries existentes del frontend TabEnviosFlex SHALL seguir funcionando sin modificación (backward-compatible)

#### Scenario: Check constraint evita incoherencias

- GIVEN el check constraint `CHK_etiqueta_envio_tipo_coherencia`
- WHEN se intenta insertar una fila con `tipo_envio='retiro_proveedor'` Y `proveedor_id=NULL`
- THEN la DB MUST rechazar con violación de check constraint

### Requirement: REQ-LOG-002 — Generación de etiqueta desde pedido

**Priority:** must
**Type:** functional

Cuando un pedido `requiere_envio=true` transiciona a `aprobado`, el sistema MUST ofrecer (no generar automático; debe ser explícito) la generación de la etiqueta de retiro vía endpoint `POST /api/administracion/compras/pedidos/{id}/generar-etiqueta-envio` con body:

```json
{ "proveedor_direccion_id": 42 }
```

El servicio MUST:
1. Validar que `pedido.requiere_envio=true` (si es false, HTTP 400 `"El pedido no requiere envío"`).
2. Validar que `proveedor_direccion_id` pertenece al `pedido.proveedor_id`. HTTP 400 si no.
3. Si `proveedor_direccion_id` no se provee, elegir la dirección del proveedor **marcada como principal** o etiquetada como `'retiro'` en `proveedor_direccion.etiqueta`. Si ninguna existe, HTTP 400 `"Proveedor sin dirección de retiro configurada"`.
4. Insertar una `etiquetas_envio` con `tipo_envio='retiro_proveedor'`, `proveedor_id=pedido.proveedor_id`, `proveedor_direccion_id=<elegida>`, `pedido_compra_id=pedido.id`, `cliente_id=NULL`, `es_manual=true`, `estado='pendiente_retiro'` (o el estado inicial convencional de TabEnviosFlex).
5. Retornar la etiqueta creada.

#### Scenario: Pedido con requiere_envio=false rechaza

- GIVEN un pedido aprobado con `requiere_envio=false`
- WHEN se invoca `POST /pedidos/{id}/generar-etiqueta-envio`
- THEN el sistema MUST responder HTTP 400 con `"El pedido no requiere envío"`

#### Scenario: Generación con dirección principal

- GIVEN un pedido aprobado con `requiere_envio=true`, `proveedor_id=7`
- AND el proveedor 7 tiene 2 direcciones: dirección id=101 (principal=true), id=102 (principal=false)
- WHEN se invoca `POST /pedidos/{id}/generar-etiqueta-envio` sin body
- THEN el sistema SHALL usar `proveedor_direccion_id=101` (la principal)
- AND se crea la etiqueta con `tipo_envio='retiro_proveedor', pedido_compra_id=pedido.id, proveedor_direccion_id=101`

#### Scenario: Proveedor sin dirección aborta

- GIVEN un pedido con `requiere_envio=true` y el proveedor no tiene direcciones cargadas
- WHEN se invoca el endpoint
- THEN el sistema MUST responder HTTP 400 con `"Proveedor sin dirección de retiro configurada"`
- AND NO SHALL crearse etiqueta

### Requirement: REQ-LOG-003 — Frontend TabEnviosFlex respeta `tipo_envio`

**Priority:** must
**Type:** functional

El componente frontend existente `TabEnviosFlex` (o `EtiquetasEnvio`) MUST actualizar su renderizado para:

1. Detectar `etiqueta.tipo_envio`.
2. Si `tipo_envio='retiro_proveedor'`:
   - Badge con texto "Retiro proveedor" (estilo distinto al badge "Cliente", ej. color azul vs verde).
   - Mostrar nombre del proveedor y su dirección (origen del retiro) en lugar de datos del cliente.
   - Link "Ver pedido" apuntando al pedido de compra asociado (`/administracion/compras/pedidos/{pedido_compra_id}`).
3. Si `tipo_envio='cliente'` (comportamiento actual): mantener exactamente el rendering existente (backward-compatible).

Las queries listado existentes (`GET /etiquetas-envio/`) MUST seguir funcionando. El frontend SHALL filtrar o agrupar por `tipo_envio` con un tab o selector.

#### Scenario: Listado muestra ambos tipos

- GIVEN hay 100 etiquetas: 95 `tipo_envio='cliente'`, 5 `tipo_envio='retiro_proveedor'`
- WHEN el usuario abre TabEnviosFlex
- THEN MUST ver las 100 etiquetas
- AND las 5 de retiro MUST mostrar badge "Retiro proveedor" con datos del proveedor

#### Scenario: Queries existentes no rompen

- GIVEN el componente del cliente consulta `GET /etiquetas-envio/?cliente_id=42`
- WHEN el backend responde
- THEN SHALL retornar solo las filas con `cliente_id=42` (naturalmente `tipo_envio='cliente'`; las de retiro tienen `cliente_id=NULL`)
- AND el componente SHALL renderizar como siempre

### Requirement: REQ-LOG-004 — Auditoría: etiqueta referencia al pedido

**Priority:** should
**Type:** functional

Al crear la etiqueta de retiro, el sistema SHOULD registrar un evento en `pedido_compra_eventos` con `tipo='etiqueta_envio_generada'`, `payload={etiqueta_envio_id, proveedor_direccion_id}`. Facilita trazabilidad bidireccional (desde el pedido se ve la etiqueta, desde la etiqueta se ve el pedido).

#### Scenario: Evento registrado

- GIVEN un pedido aprobado con `requiere_envio=true`
- WHEN se genera la etiqueta exitosamente
- THEN se inserta en `pedido_compra_eventos` una fila con `tipo='etiqueta_envio_generada'`
- AND el payload contiene el `etiqueta_envio_id` y la `proveedor_direccion_id` usada

## OPEN QUESTIONS

- OPEN_QUESTION-LOG-01: ¿La etiqueta se genera automáticamente al aprobar el pedido (si `requiere_envio=true`) o requiere acción explícita? Decisión del proposal: acción explícita (evitar side-effects silenciosos en la aprobación). Confirmado.
- OPEN_QUESTION-LOG-02: ¿La columna `proveedor_direccion.etiqueta='retiro'` es un valor convencional a agregar o hay ya un flag `es_principal`/`es_retiro`? Verificar en diseño el schema real de `proveedor_direccion.py`.
- OPEN_QUESTION-LOG-03: ¿Se permite regenerar una etiqueta si ya existe una para el pedido? v1 recomendado: NO (HTTP 409 si ya existe). Si hay que cambiar dirección, anular la etiqueta vieja y crear nueva. Confirmar en diseño.
