# Spec Delta — Recepción de Mercadería por Depósito

**Change:** compras-recepcion-deposito
**Capability:** recepcion-deposito
**Status:** draft
**Date:** 2026-06-18
**Depends on:** compras-vincular-orden-compra-erp Slice 1 (merged)

---

## Purpose

Close the receiving loop for purchase orders: a warehouse operator with the
`deposito.recibir_mercaderia` permission can register partial or full goods
receipts against a linked ERP purchase order, accumulating receipts across
multiple delivery batches, and transition the pedido through well-defined
states (`pagado → recibido / con_faltantes`).

ERP tables remain **read-only** throughout. All state changes, receipt records,
and events live exclusively in pricing-app tables.

---

## SLICE A — Backend (data model, endpoints, permissions, events)

---

### REQ-RD-001 — Table `pedido_compra_ingresos` (append-only)

**Priority:** must
**Type:** data-model

The table `pedido_compra_ingresos` MUST exist with the following schema.
If it was not created by the prior change (compras-vincular-orden-compra-erp
Slice 2), this change creates it via Alembic migration.

| Column | Type | Constraints |
|---|---|---|
| `id` | BigInteger | PK, auto-increment |
| `pedido_id` | BigInteger | FK `pedidos_compra.id` ON DELETE RESTRICT, NOT NULL |
| `oc_comp_id` | Integer | NOT NULL (snapshot) |
| `oc_bra_id` | Integer | NOT NULL (snapshot) |
| `oc_poh_id` | BigInteger | NOT NULL (snapshot) |
| `pod_id` | Integer | NOT NULL (line identity from ERP) |
| `item_id` | BigInteger | NOT NULL (snapshot) |
| `stor_id` | Integer | NOT NULL (snapshot) |
| `cantidad_recibida` | Numeric(18,6) | NOT NULL, CHECK > 0 |
| `fecha_ingreso` | Date | NOT NULL, DEFAULT CURRENT_DATE |
| `usuario_id` | Integer | FK `usuarios.id` ON DELETE RESTRICT, NOT NULL |
| `observaciones` | Text | nullable |
| `created_at` | DateTime | NOT NULL, DEFAULT UTC now |

Indexes:
- `ix_pci_pedido` on `(pedido_id)`
- `ix_pci_oc_linea` on `(oc_comp_id, oc_bra_id, oc_poh_id, pod_id)`

Rules:
- Append-only: no UPDATE or DELETE is ever issued against this table by the
  application. Row creation is the only write operation.
- `cantidad_recibida` CHECK > 0 enforced both at DB level and service layer
  (HTTP 422 before reaching the DB).

#### Scenario: Migration creates table with correct schema

- GIVEN a DB with the Slice 1 migration of compras-vincular-orden-compra-erp applied
- WHEN the Alembic migration for this change runs (`alembic upgrade head`)
- THEN `pedido_compra_ingresos` MUST exist with all columns, types, and CHECK
  constraint as described
- AND both indexes MUST exist

#### Scenario: Direct INSERT with cantidad_recibida = 0 is rejected at DB level

- GIVEN a valid pedido and OC context
- WHEN an INSERT with `cantidad_recibida = 0` is attempted
- THEN the DB CHECK constraint MUST reject it

---

### REQ-RD-002 — States `recibido` and `con_faltantes` on `pedidos_compra`

**Priority:** must
**Type:** data-model

The `pedidos_compra.estado` column (String(24) + CheckConstraint) MUST be
extended to allow two new values: `recibido` and `con_faltantes`.

The updated CheckConstraint MUST enumerate all valid values:
`borrador`, `pendiente_aprobacion`, `aprobado`, `rechazado`, `cancelado`,
`pagado_parcial`, `pagado`, `con_faltantes`, `recibido`.

Migration: `op.execute` to drop and recreate the constraint. Backward-compatible
(existing rows retain valid values).

#### Scenario: Migration adds new states without breaking existing rows

- GIVEN existing pedidos with states in the original set
- WHEN the Alembic migration runs
- THEN all existing rows MUST remain valid
- AND INSERT with `estado='recibido'` MUST succeed
- AND INSERT with `estado='con_faltantes'` MUST succeed
- AND INSERT with `estado='en_camino'` (invalid) MUST be rejected by the constraint

---

### REQ-RD-003 — Permission `deposito.recibir_mercaderia`

**Priority:** must
**Type:** security

A new permission `deposito.recibir_mercaderia` MUST be created via migration
seed (INSERT into the permissions table). It MUST NOT be assigned to any role
by default; role assignment is done manually by an admin.

This permission gates:
- The `deposito` tab in the frontend (enforced by the API: 403 without it).
- ALL reception endpoints: `GET /recepcion/saldos`, `POST /recepcion/ingresos`,
  `POST /recepcion/confirmar-pedido`, `GET /recepcion/eventos`.
- The retiro action (`POST /pedidos/{id}/generar-etiqueta-envio`) when triggered
  from the reception flow.

**Single-permission rule:** ALL new reception endpoints (`recepcion/saldos`,
`recepcion/ingresos`, `recepcion/confirmar-pedido`, `recepcion/eventos`) require
ONLY `deposito.recibir_mercaderia`. `administracion.gestionar_ordenes_compra` does
NOT grant access to reception actions — warehouse is a distinct profile.

#### Scenario: User without deposito.recibir_mercaderia is rejected on all reception endpoints

- GIVEN an authenticated user with no permissions (or only unrelated permissions)
- WHEN the user calls any of: `GET /recepcion/saldos`, `POST /recepcion/ingresos`,
  `POST /recepcion/confirmar-pedido`, `GET /recepcion/eventos`
- THEN EACH endpoint MUST return HTTP 403
- AND no DB read or write MUST be performed

#### Scenario: gestionar_ordenes_compra alone does NOT grant access to reception endpoints

- GIVEN an authenticated user with `administracion.gestionar_ordenes_compra`
  but NOT `deposito.recibir_mercaderia`
- WHEN any reception endpoint is called
- THEN the request MUST be rejected with HTTP 403

#### Scenario: Permission seed creates the permission record

- GIVEN a freshly migrated DB
- WHEN the seed is applied
- THEN a row with `codigo='deposito.recibir_mercaderia'` MUST exist in the
  permissions table
- AND no role-permission association for this code MUST exist

---

### REQ-RD-004 — `GET /pedidos/{id}/recepcion/saldos`

**Priority:** must
**Type:** functional

Returns the reception summary for a pedido: whether an OC is linked, and if
so, per-line balance information.

**Permission required:** `deposito.recibir_mercaderia`

Response schema:

```json
{
  "pedido_id": 1,
  "tiene_oc": true,
  "estado": "pagado",
  "requiere_envio": false,
  "lineas": [
    {
      "pod_id": 1,
      "item_id": 5001,
      "item_nombre": "Tornillo M8",
      "stor_id": 3,
      "deposito_nombre": "Depósito Central",
      "pod_qty": 100.0,
      "cantidad_recibida_total": 0.0,
      "saldo_pendiente": 100.0
    }
  ]
}
```

Rules:
- `item_nombre` is resolved via LEFT JOIN to `productos_erp`. If no match, fall
  back to `item_id` cast as string (phantom item). The line MUST always appear.
- `saldo_pendiente = pod_qty - SUM(cantidad_recibida)` from all existing ingresos
  for this `pedido_id` + `pod_id`.
- `pod_qty` = ERP field `pod_qty − COALESCE(pod_confirmedqty, 0)`.
- If `tiene_oc = false`, `lineas` MUST be an empty array `[]`.
- Only pedidos in states `pagado`, `con_faltantes` or `recibido` may be queried
  without error. Pedidos in other states return HTTP 409 with detail
  `"Pedido not in a receivable state"`.

#### Scenario: CON OC — lines returned with saldo computed

- GIVEN pedido P1 (estado=`pagado`) linked to OC #12345
- AND OC has 2 lines: pod_id=1 (qty=100) and pod_id=2 (qty=50)
- AND 1 prior ingreso: pod_id=1 cantidad_recibida=60
- WHEN `GET /pedidos/P1/recepcion/saldos`
- THEN `tiene_oc=true`, `lineas` has 2 entries
- AND `lineas[pod_id=1].saldo_pendiente = 40`
- AND `lineas[pod_id=2].saldo_pendiente = 50`

#### Scenario: Phantom item — fallback to item_id string

- GIVEN pedido P1 linked to OC with pod_id=9 having item_id=99999 (no match in productos_erp)
- WHEN `GET /recepcion/saldos`
- THEN the line for pod_id=9 MUST appear with `item_nombre="99999"` (fallback)
- AND the line MUST NOT be omitted

#### Scenario: SIN OC — lineas is empty, tiene_oc=false

- GIVEN pedido P1 with no linked OC, estado=`pagado`
- WHEN `GET /recepcion/saldos`
- THEN `tiene_oc=false`, `lineas=[]`

#### Scenario: Pedido not found → 404

- GIVEN pedido_id=9999 does not exist
- WHEN `GET /recepcion/saldos`
- THEN HTTP 404 with detail `"Pedido not found"`

#### Scenario: Permission required

- GIVEN user without `deposito.recibir_mercaderia`
- WHEN `GET /recepcion/saldos`
- THEN HTTP 403

#### Scenario: ERP tables are not written

- GIVEN any call to this endpoint
- THEN NO INSERT, UPDATE, or DELETE SHALL be executed against ERP mirror tables

---

### REQ-RD-005 — `POST /pedidos/{id}/recepcion/ingresos`

**Priority:** must
**Type:** functional

Registers a batch (tanda) of goods received for a pedido WITH a linked OC.
Inserts one row per line into `pedido_compra_ingresos`, updates the pedido's
`estado`, and emits a `compras_eventos` record.

**Permission required:** `deposito.recibir_mercaderia` (only).

Request body:

```json
{
  "lineas": [
    { "pod_id": 1, "cantidad_recibida": 60.0 },
    { "pod_id": 2, "cantidad_recibida": 0.0 }
  ],
  "observaciones": "Primera entrega"
}
```

Rules:
- Lines with `cantidad_recibida = 0` are silently ignored; no row is inserted for them.
- All non-zero lines are processed atomically (all succeed or all fail).
- The pedido MUST have a linked OC. If not: HTTP 409 `"Pedido has no linked OC"`.
- The pedido MUST be in state `pagado` or `con_faltantes`. If in `recibido`: HTTP
  409 `"Pedido already fully received"`. Other states: HTTP 409 `"Pedido not in a
  receivable state"`.
- For each non-zero line, `pod_id` MUST exist in `tb_purchase_order_detail` for
  the linked OC. If not: HTTP 422.
- **Over-receipt**: for each line, if `cantidad_recibida_tanda > saldo_pendiente`,
  the whole request MUST be rejected HTTP 409 with detail
  `"Over-receipt: pod_id {X} — saldo pendiente es {saldo}, solicitado {qty}"`.
  The check runs before any INSERT.
- `usuario_id` is taken from `get_current_user`, not from the request body.

**State transition after successful insert:**
- If all lines now have `saldo_pendiente = 0`: `estado → recibido` and event type =
  `recepcion_registrada`.
- If any line still has `saldo_pendiente > 0`: `estado → con_faltantes` and event
  type = `recepcion_con_faltantes`.

Response (HTTP 201):

```json
{
  "pedido_id": 1,
  "estado_nuevo": "con_faltantes",
  "ingresos_creados": [{ "id": 7, "pod_id": 1, "cantidad_recibida": 60.0 }],
  "saldos": [
    { "pod_id": 1, "saldo_pendiente": 40.0 },
    { "pod_id": 2, "saldo_pendiente": 50.0 }
  ]
}
```

#### Scenario: Partial batch → estado con_faltantes

- GIVEN P1 (estado=`pagado`) linked to OC with pod_id=1 (qty=100), pod_id=2 (qty=50)
- WHEN `POST /recepcion/ingresos` with `{lineas:[{pod_id:1, cantidad_recibida:60}]}`
- THEN HTTP 201
- AND 1 row inserted in `pedido_compra_ingresos` (pod_id=1, qty=60)
- AND P1.estado = `con_faltantes`
- AND event `recepcion_con_faltantes` emitted with payload containing pod_id=1
  (saldo_pendiente=40) and pod_id=2 (saldo_pendiente=50)

#### Scenario: Complete batch → estado recibido

- GIVEN P1 (estado=`pagado`), OC with only pod_id=1 (qty=100)
- WHEN `POST /recepcion/ingresos` with `{lineas:[{pod_id:1, cantidad_recibida:100}]}`
- THEN HTTP 201
- AND P1.estado = `recibido`
- AND event `recepcion_registrada` emitted

#### Scenario: Second batch from con_faltantes completes → estado recibido

- GIVEN P1 (estado=`con_faltantes`), pod_id=1 saldo_pendiente=40, pod_id=2 saldo_pendiente=50
- WHEN `POST /recepcion/ingresos` with both lines filled to their saldo
- THEN HTTP 201, P1.estado = `recibido`

#### Scenario: Second batch from con_faltantes still partial → stays con_faltantes

- GIVEN P1 (estado=`con_faltantes`), pod_id=1 saldo=40, pod_id=2 saldo=50
- WHEN `POST /recepcion/ingresos` with pod_id=1 qty=20 only
- THEN HTTP 201, P1.estado = `con_faltantes`

#### Scenario: Over-receipt → 409, no inserts

- GIVEN P1 linked to OC, pod_id=1 (saldo=20)
- WHEN `POST /recepcion/ingresos` with pod_id=1 cantidad_recibida=30
- THEN HTTP 409 with `"Over-receipt: pod_id 1 — saldo pendiente es 20, solicitado 30"`
- AND no row inserted in `pedido_compra_ingresos`
- AND P1.estado unchanged

#### Scenario: Multi-line batch is atomic — one over-receipt rolls back all

- GIVEN P1, pod_id=1 saldo=50, pod_id=2 saldo=50
- WHEN `POST /recepcion/ingresos` with `[{pod_id:1, qty:50}, {pod_id:2, qty:60}]`
- THEN HTTP 409
- AND no row inserted for either pod_id

#### Scenario: Pedido is recibido → 409

- GIVEN P1.estado = `recibido`
- WHEN `POST /recepcion/ingresos`
- THEN HTTP 409 `"Pedido already fully received"`

#### Scenario: Pedido without OC → 409

- GIVEN P1 has no linked OC
- WHEN `POST /recepcion/ingresos`
- THEN HTTP 409 `"Pedido has no linked OC"`

#### Scenario: Lines with cantidad_recibida=0 are silently ignored

- GIVEN P1 linked to OC, pod_id=1 saldo=100, pod_id=2 saldo=50
- WHEN `POST /recepcion/ingresos` with `[{pod_id:1, qty:0}, {pod_id:2, qty:30}]`
- THEN HTTP 201 (only pod_id=2 processed)
- AND only 1 row inserted (pod_id=2)
- AND pod_id=1 saldo unchanged

#### Scenario: Permission required

- GIVEN user with no relevant permission
- WHEN `POST /recepcion/ingresos`
- THEN HTTP 403

#### Scenario: Pedido not found → 404

- GIVEN pedido_id does not exist
- WHEN `POST /recepcion/ingresos`
- THEN HTTP 404

#### Scenario: ERP tables never written

- GIVEN any successful call
- THEN NO INSERT, UPDATE, or DELETE on ERP mirror tables (`tb_purchase_order_*`,
  `tb_storage`)

---

### REQ-RD-006 — `POST /pedidos/{id}/recepcion/confirmar-pedido`

**Priority:** must
**Type:** functional

Confirms reception at the pedido level for pedidos WITHOUT a linked OC. Does not
create rows in `pedido_compra_ingresos`. Updates pedido estado and emits event.

**Permission required:** `deposito.recibir_mercaderia`

Request body:

```json
{
  "completo": true,
  "observaciones": "Llegó completo sin OC vinculada"
}
```

Rules:
- The pedido MUST have no linked OC. If it has one: HTTP 409
  `"Pedido has OC linked. Use /recepcion/ingresos instead."`.
- The pedido MUST be in state `pagado` or `con_faltantes`.
- If `completo=true`: `estado → recibido`, event type = `recepcion_registrada`.
- If `completo=false`: `estado → con_faltantes`, event type =
  `recepcion_con_faltantes`. `observaciones` is required in this case (HTTP 422
  if absent).
- No row is created in `pedido_compra_ingresos` (no item breakdown available).
- Event payload for this mode: `{ "modo": "sin_oc", "completo": true/false, "observaciones": "..." }`.

Response (HTTP 200):

```json
{ "pedido_id": 1, "estado_nuevo": "recibido" }
```

#### Scenario: SIN OC, completo=true → recibido

- GIVEN P1 (estado=`pagado`) with no linked OC
- WHEN `POST /recepcion/confirmar-pedido` with `{completo:true}`
- THEN HTTP 200, P1.estado = `recibido`
- AND event `recepcion_registrada` emitted with `modo=sin_oc`
- AND NO row created in `pedido_compra_ingresos`

#### Scenario: SIN OC, completo=false with observaciones → con_faltantes

- GIVEN P1 (estado=`pagado`) with no linked OC
- WHEN `POST /recepcion/confirmar-pedido` with `{completo:false, observaciones:"Faltaron 3 ítems"}`
- THEN HTTP 200, P1.estado = `con_faltantes`
- AND event `recepcion_con_faltantes` emitted

#### Scenario: completo=false without observaciones → 422

- GIVEN P1 with no linked OC
- WHEN `POST /recepcion/confirmar-pedido` with `{completo:false}` (no observaciones)
- THEN HTTP 422

#### Scenario: Pedido has OC → 409

- GIVEN P1 has a linked OC
- WHEN `POST /recepcion/confirmar-pedido`
- THEN HTTP 409 `"Pedido has OC linked. Use /recepcion/ingresos instead."`

#### Scenario: Permission required

- GIVEN user without `deposito.recibir_mercaderia`
- WHEN `POST /recepcion/confirmar-pedido`
- THEN HTTP 403

#### Scenario: Pedido not found → 404

- GIVEN pedido_id does not exist
- THEN HTTP 404

---

### REQ-RD-007 — State Machine for `pedidos_compra.estado`

**Priority:** must
**Type:** functional

The reception service MUST enforce the following transition table. Any transition
not listed MUST be rejected (HTTP 409 `"Invalid state transition"`).

| From | Trigger | To | Terminal |
|---|---|---|---|
| `pagado` | tanda completa (saldos=0) | `recibido` | yes |
| `pagado` | tanda parcial (saldo>0) | `con_faltantes` | no |
| `pagado` | confirmar-pedido completo=true | `recibido` | yes |
| `pagado` | confirmar-pedido completo=false | `con_faltantes` | no |
| `con_faltantes` | tanda completa (saldos=0) | `recibido` | yes |
| `con_faltantes` | tanda parcial (saldo>0) | `con_faltantes` | no (self) |
| `con_faltantes` | confirmar-pedido completo=true | `recibido` | yes |
| `con_faltantes` | confirmar-pedido completo=false | `con_faltantes` | no (self) |
| `recibido` | any ingreso attempt | 409 | — |
| any other | any reception endpoint | 409 | — |

`recibido` is terminal. No re-opening is in scope for this change.

#### Scenario: pagado → recibido (direct)

- GIVEN P1.estado = `pagado`
- WHEN a complete tanda is received
- THEN P1.estado = `recibido`

#### Scenario: pagado → con_faltantes → con_faltantes → recibido (multi-batch)

- GIVEN P1.estado = `pagado`
- WHEN tanda 1 (partial) → P1.estado = `con_faltantes`
- AND tanda 2 (partial again) → P1.estado = `con_faltantes`
- AND tanda 3 (completes all saldos) → P1.estado = `recibido`
- THEN each transition MUST be logged as a separate event

#### Scenario: State borrador is not a valid reception source

- GIVEN P1.estado = `borrador`
- WHEN `POST /recepcion/ingresos`
- THEN HTTP 409 `"Pedido not in a receivable state"`

---

### REQ-RD-008 — Events in `compras_eventos`

**Priority:** must
**Type:** functional

Every successful reception operation MUST insert one record in `compras_eventos`
(append-only, no schema changes to the table; only new `tipo` values).

New event types: `recepcion_registrada`, `recepcion_con_faltantes`.

`entidad_tipo = 'pedido_compra'`, `entidad_id = pedido_id`.

**Payload schema for CON OC mode:**

```json
{
  "modo": "con_oc",
  "lineas": [
    {
      "pod_id": 1,
      "item_id": 5001,
      "cantidad_recibida": 60.0,
      "saldo_pendiente": 40.0
    }
  ],
  "requiere_envio": false,
  "retiro_generado": false
}
```

**Payload schema for SIN OC mode:**

```json
{
  "modo": "sin_oc",
  "completo": true,
  "observaciones": "...",
  "requiere_envio": false,
  "retiro_generado": false
}
```

Rules:
- `retiro_generado` is `true` only when a `generar-etiqueta-envio` call was made
  in the same request flow.
- Only lines with `cantidad_recibida > 0` appear in `lineas`.
- For `recepcion_con_faltantes`, the `lineas` array MUST include ALL OC lines
  (not just those received in this batch) so faltantes are fully auditable.
  Include `cantidad_recibida=0` and `saldo_pendiente=full_qty` for unreceived lines.

#### Scenario: Event emitted after partial batch

- GIVEN P1 (CON OC), pod_id=1 saldo=100, pod_id=2 saldo=50
- WHEN tanda: pod_id=1 qty=60 → estado con_faltantes
- THEN event of type `recepcion_con_faltantes` MUST be in `compras_eventos`
- AND payload.lineas MUST contain both pod_id=1 (qty_recibida=60, saldo=40)
  AND pod_id=2 (qty_recibida=0, saldo=50)

#### Scenario: Event emitted after completing receipt

- GIVEN P1, after tanda that completes all saldos → estado recibido
- THEN event of type `recepcion_registrada` MUST be emitted
- AND all `lineas[i].saldo_pendiente` MUST be 0

#### Scenario: Event emitted for SIN OC confirmation

- GIVEN P1 (SIN OC), confirmar-pedido completo=false
- THEN event type = `recepcion_con_faltantes`, payload.modo = `sin_oc`

---

### REQ-RD-009 — `GET /pedidos/{id}/recepcion/eventos`

**Priority:** should
**Type:** functional

Returns all `compras_eventos` records for this pedido with `tipo` in
`{recepcion_registrada, recepcion_con_faltantes}`, ordered by `created_at` DESC.

**Permission required:** `deposito.recibir_mercaderia`

Response:

```json
{
  "pedido_id": 1,
  "eventos": [
    {
      "id": 42,
      "tipo": "recepcion_con_faltantes",
      "created_at": "2026-06-18T10:00:00Z",
      "usuario_nombre": "Ana García",
      "payload": { ... }
    }
  ]
}
```

This endpoint MAY be implemented by filtering the existing events endpoint by
type rather than adding a new route, provided the result schema matches.

#### Scenario: Returns reception events in reverse chronological order

- GIVEN P1 with 2 reception events
- WHEN `GET /recepcion/eventos`
- THEN both events returned, newest first

#### Scenario: No events → empty list

- GIVEN P1 with no reception events
- WHEN `GET /recepcion/eventos`
- THEN HTTP 200, `eventos: []`

---

### REQ-RD-010 — Retiro del proveedor (requiere_envio=true)

**Priority:** must
**Type:** functional

When `pedidos_compra.requiere_envio = true`, the reception flow MUST allow
triggering a carrier pickup from the supplier via the existing
`POST /pedidos/{id}/generar-etiqueta-envio` endpoint.

This spec constrains the BEHAVIOR of the flow, not the implementation of
`generar-etiqueta-envio` (already implemented).

Rules:
- Triggering a retiro requires first fetching the supplier's addresses via
  `GET /proveedores/{proveedor_id}/direcciones`.
- The user selects one `proveedor_direccion_id` from that list.
- The system calls `POST /pedidos/{id}/generar-etiqueta-envio` with the selected
  `proveedor_direccion_id`, creating an `EtiquetaEnvio` of type `retiro_proveedor`.
- The retiro flow is INDEPENDENT of receipt registration: a user may trigger a
  retiro before, during, or after recording ingresos.
- TabEnviosFlex MUST NOT be mounted or imported. Only the endpoint is called.
- `retiro_generado = true` is set in the event payload when both a retiro and an
  ingreso occur in the same request (optional chaining; the backend may allow them
  to be separate calls).

#### Scenario: requiere_envio=true — retiro triggers generar-etiqueta-envio

- GIVEN P1 with `requiere_envio=true`, proveedor has direccion_id=5
- WHEN `POST /pedidos/P1/generar-etiqueta-envio` with `{proveedor_direccion_id: 5}`
- THEN HTTP 201, an `EtiquetaEnvio` of type `retiro_proveedor` is created
- AND TabEnviosFlex is NOT involved

#### Scenario: requiere_envio=false — retiro action is not offered

- GIVEN P1 with `requiere_envio=false`
- THEN the frontend MUST NOT render the "Cargar retiro" button (spec: the saldos
  endpoint returns `requiere_envio=false`; the UI uses this flag)

---

### REQ-RD-011 — item_nombre JOIN with fallback

**Priority:** must
**Type:** functional

`GET /recepcion/saldos` (and any endpoint that returns item names) MUST resolve
`item_nombre` via LEFT JOIN to `productos_erp` on `item_id`. If no match:
`item_nombre = str(item_id)`.

The LEFT JOIN MUST NOT filter out lines. Every line in the OC MUST appear
regardless of whether `item_id` exists in `productos_erp`.

This mirrors the requirement established in REQ-OC-006 of the prior change,
extended to include `item_nombre` in the response.

#### Scenario: All items resolved

- GIVEN OC with pod_id=1 (item_id=5001, present in productos_erp as "Tornillo M8")
- WHEN `GET /recepcion/saldos`
- THEN `item_nombre = "Tornillo M8"`

#### Scenario: Phantom item — fallback

- GIVEN OC with pod_id=2 (item_id=99999, NOT in productos_erp)
- WHEN `GET /recepcion/saldos`
- THEN `item_nombre = "99999"` (string representation of item_id)
- AND the line MUST appear in the response

---

### REQ-RD-012 — ERP tables remain read-only

**Priority:** must
**Type:** non-functional

No service, router, or migration in this change SHALL execute INSERT, UPDATE, or
DELETE against `tb_purchase_order_header`, `tb_purchase_order_detail`,
`tb_purchase_order_detailx` (if it exists), or `tb_storage`.

This MUST be verifiable in a pytest integration test by asserting the only tables
written to are: `pedidos_compra`, `pedido_compra_ingresos`, `compras_eventos`.

#### Scenario: Receipt recording writes only to pricing-app tables

- GIVEN any successful `POST /recepcion/ingresos` call
- THEN write operations MUST be limited to `pedidos_compra` (estado update),
  `pedido_compra_ingresos` (INSERT), and `compras_eventos` (INSERT)
- AND no ERP mirror table MUST be written

---

## API Contract Summary (Slice A)

| Method | Path | Permission | Success | Notable 4xx |
|---|---|---|---|---|
| GET | `/pedidos/{id}/recepcion/saldos` | `deposito.recibir_mercaderia` | 200 | 403, 404, 409 |
| POST | `/pedidos/{id}/recepcion/ingresos` | `deposito.recibir_mercaderia` | 201 | 403, 404, 409, 422 |
| POST | `/pedidos/{id}/recepcion/confirmar-pedido` | `deposito.recibir_mercaderia` | 200 | 403, 404, 409, 422 |
| GET | `/pedidos/{id}/recepcion/eventos` | `deposito.recibir_mercaderia` | 200 | 403, 404 |

Reused endpoints (no changes):
- `GET /proveedores/{id}/direcciones` — list supplier addresses for retiro flow
- `POST /pedidos/{id}/generar-etiqueta-envio` — trigger carrier pickup

---

## SLICE B — Frontend (tab depósito, UI recepción, mini-modal retiro)

---

### REQ-RD-FE-001 — Tab `deposito` in `AdministracionCompras.jsx`

**Priority:** must
**Type:** ui

A new tab entry `{ id: "deposito", label: "Depósito" }` MUST be added to the
TABS array in `AdministracionCompras.jsx`.

The tab MUST only be rendered when the current user has `deposito.recibir_mercaderia`.
If the user lacks the permission, the tab MUST NOT appear and the route MUST return
403 from the API (frontend relies on the API gate, but also hides the tab proactively
via the existing permission helper).

**Gate:** Slice B MUST NOT be implemented before `sdd-design` produces stitch
mockups for `TabRecepcionDeposito.jsx` and `ModalCargarRetiro.jsx`.

#### Scenario: Tab visible with permission

- GIVEN user has `deposito.recibir_mercaderia`
- WHEN `AdministracionCompras.jsx` renders
- THEN a "Depósito" tab MUST appear in the tab bar

#### Scenario: Tab absent without permission

- GIVEN user does NOT have `deposito.recibir_mercaderia`
- WHEN `AdministracionCompras.jsx` renders
- THEN no "Depósito" tab MUST appear

---

### REQ-RD-FE-002 — `TabRecepcionDeposito.jsx` — Pedido list

**Priority:** must
**Type:** ui

The component MUST:
- Fetch all pedidos in states `pagado` and `con_faltantes`.
- Render each pedido as a collapsible accordion entry.
- Show a visual indicator for pedidos with `requiere_envio=true`.
- Support an optional filter by `requiere_envio` (all / solo retiro / solo entrega).

#### Scenario: List shows pagado and con_faltantes pedidos

- GIVEN 3 pedidos: P1 (pagado), P2 (con_faltantes), P3 (recibido)
- WHEN the deposito tab loads
- THEN P1 and P2 MUST appear; P3 MUST NOT appear

---

### REQ-RD-FE-003 — Accordion body — CON OC mode

**Priority:** must
**Type:** ui

When a pedido has a linked OC (`tiene_oc=true`), opening the accordion MUST
fetch `GET /recepcion/saldos` and render a receipt table with:

- One row per OC line: item name, deposito name, saldo pendiente, input field for
  cantidad_recibida in this batch.
- A checkbox per line that, when checked, auto-fills the input with `saldo_pendiente`.
- A "Marcar todo" control that checks all checkboxes and fills all inputs.
- Button "Recibido": enabled only when all inputs would bring every saldo to 0.
- Button "Marcar con faltantes": enabled when at least one saldo > 0 after applying
  current inputs.

On submit:
- Calls `POST /recepcion/ingresos` with the non-zero lines.
- Shows a success toast and refreshes the accordion.
- On 409 (over-receipt), shows an error message inline.

#### Scenario: Checkbox fills input with saldo

- GIVEN line pod_id=1 with saldo_pendiente=40
- WHEN user checks the checkbox for that line
- THEN the input for that line MUST be auto-filled with 40

#### Scenario: "Recibido" button disabled when saldo remains

- GIVEN two lines with saldo_pendiente > 0, user fills only one input
- THEN "Recibido" button MUST be disabled

#### Scenario: "Marcar todo" fills all inputs

- GIVEN lines with various saldos
- WHEN user clicks "Marcar todo"
- THEN ALL inputs MUST be filled with their respective `saldo_pendiente` values

---

### REQ-RD-FE-004 — Accordion body — SIN OC mode

**Priority:** must
**Type:** ui

When `tiene_oc=false`, the accordion body MUST:
- Show a notice: "Este pedido no tiene OC vinculada. No es posible registrar por ítem."
- Offer two buttons: "Confirmar recibido" and "Marcar con faltantes".
- "Marcar con faltantes" MUST open a text input for observaciones (required).
- On confirm, calls `POST /recepcion/confirmar-pedido`.

#### Scenario: Notice shown for pedido without OC

- GIVEN P1 with no linked OC
- WHEN accordion is opened
- THEN notice text about missing OC MUST be visible
- AND item-level receipt table MUST NOT appear

---

### REQ-RD-FE-005 — `ModalCargarRetiro.jsx` — supplier pickup

**Priority:** must
**Type:** ui

For pedidos with `requiere_envio=true`, a "Cargar retiro" button MUST appear in
the accordion header or body.

Clicking it opens a modal that:
- Fetches `GET /proveedores/{proveedor_id}/direcciones`.
- Renders the list of addresses for selection.
- On selection, triggers `POST /pedidos/{id}/generar-etiqueta-envio` with the
  chosen `proveedor_direccion_id`.
- Shows a success toast on HTTP 201.
- Does NOT render or import `TabEnviosFlex`.

#### Scenario: Modal lists supplier addresses

- GIVEN P1 with requiere_envio=true, proveedor has 2 addresses
- WHEN "Cargar retiro" is clicked
- THEN modal opens with 2 address options

#### Scenario: Selecting address and confirming triggers generar-etiqueta-envio

- GIVEN modal open, user selects address_id=5
- WHEN user confirms
- THEN `POST /pedidos/P1/generar-etiqueta-envio` is called with `{proveedor_direccion_id:5}`
- AND success toast is shown

#### Scenario: requiere_envio=false — button not shown

- GIVEN P1 with requiere_envio=false
- THEN "Cargar retiro" MUST NOT appear

---

## Cross-Cutting Requirements

### REQ-RD-X001 — Strict TDD: all backend requirements testable by pytest

**Priority:** must
**Type:** testing

Every backend REQ in this spec MUST have at least one corresponding pytest test in
`backend/tests/integration/test_recepcion_deposito_endpoints.py`.

Minimum test coverage:
- `GET /recepcion/saldos`: CON OC (with saldo), SIN OC, phantom item fallback,
  403, 404.
- `POST /recepcion/ingresos`: partial batch (→con_faltantes), complete batch
  (→recibido), over-receipt (409), atomic rollback on partial over-receipt,
  pedido already recibido (409), pedido without OC (409), zero-qty lines ignored,
  403, 404.
- `POST /recepcion/confirmar-pedido`: completo=true (→recibido), completo=false
  (→con_faltantes), missing observaciones on completo=false (422), pedido with OC
  (409), 403, 404.
- State machine: pagado→recibido, pagado→con_faltantes,
  con_faltantes→recibido, recibido rejects ingreso.
- Events: `recepcion_registrada` and `recepcion_con_faltantes` emitted with
  correct payload structure.
- ERP read-only: assert no writes to ERP mirror tables.
- Permission isolation: reception endpoints reject `gestionar_ordenes_compra`-only users (403); ONLY `deposito.recibir_mercaderia` grants access.

---

### REQ-RD-X002 — Pedido not found → 404 (all endpoints)

**Priority:** must
**Type:** functional

For every endpoint using `{pedido_id}`, if the pedido does not exist the response
MUST be HTTP 404 with detail `"Pedido not found"`. This check runs before
permission checks against OC or ingreso data.

---

## Assumptions made at spec level (open questions resolved)

| ID | Question from proposal | Resolution in this spec |
|---|---|---|
| D1 | `con_faltantes` vs `recepcion_parcial` | `con_faltantes` is sufficient. No `recepcion_parcial` state created. |
| D2 | POST ingresos: only `deposito.recibir_mercaderia` or also `gestionar_ordenes_compra`? | ONLY `deposito.recibir_mercaderia` (LOCKED by user). Reception is a distinct warehouse profile. |
| D3 | Over-receipt: block or tolerate? | Hard block 409 in v1. REQ-RD-005. |
| D4 | Re-open `recibido`? | Out of scope. `recibido` is terminal. REQ-RD-007. |
| D5 | Push notification on `con_faltantes`? | Only event persisted; no push in this change. REQ-RD-008. |
| D6 | Filter by depot/branch of logged-in operator? | v1: shows all. No stor_id filter. |
| R-DUP | Slice 2 of prior change — table already exists? | Spec treats `pedido_compra_ingresos` as potentially absent. Migration conditionally creates it. Design MUST confirm real DB state and adjust migration accordingly. **Flagged as design-time risk.** |

---

## Out of Scope (explicit exclusions)

1. Writing stock or any ERP table.
2. Re-opening a `recibido` pedido (anulación/devolución).
3. Per-item receipt for pedidos SIN OC.
4. Push/notification to purchasing team on `con_faltantes`.
5. Filtering pedido list by operator's `stor_id`.
6. Over-receipt with configurable tolerance.
7. Mounting or importing TabEnviosFlex.
