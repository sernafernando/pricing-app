# Spec Delta — Vincular Orden de Compra ERP al Pedido + Ingreso por Depósito

**Change:** compras-vincular-orden-compra-erp
**Capability:** vincular-oc
**Status:** draft

## Purpose

Link a purchase order (OC) from the read-only ERP mirror (`tb_purchase_order_header` / `tb_purchase_order_detail`) to a pricing-app purchase request (`pedidos_compra`). Extends the existing invoice-linking pattern (one-to-one, mutable, three nullable FK-logical columns). Adds a per-depot breakdown view and — in a second slice — a reception confirmation workflow that accumulates partial receipts without ever writing to ERP tables.

ERP tables (`tb_purchase_order_header`, `tb_purchase_order_detail`, `tb_storage`) are **read-only mirrors** throughout. All linking, ingreso records, and state changes live exclusively in pricing-app tables.

---

## SLICE 1 — OC Link + Read-Only Breakdown

### Requirement: REQ-OC-001 — Three nullable link columns on `pedidos_compra`

**Priority:** must
**Type:** data-model

The `pedidos_compra` table MUST gain exactly three nullable columns to hold the OC link:

| Column | Type | Description |
|--------|------|-------------|
| `oc_comp_id` | Integer, nullable | Logical FK to `tb_purchase_order_header.comp_id` |
| `oc_bra_id` | Integer, nullable | Logical FK to `tb_purchase_order_header.bra_id` |
| `oc_poh_id` | BigInteger, nullable | Logical FK to `tb_purchase_order_header.poh_id` |

Rules:
- The three columns are ALL NULL (unlinked) or ALL NOT NULL (linked). A partially-filled state is invalid.
- No physical FK constraint against the ERP mirror (same pattern as `ct_transaction_id`).
- A partial index on `oc_poh_id IS NOT NULL` MUST be created.
- Migration: Alembic, three `op.add_column` + partial index; backward-compatible (no NOT NULL, no default).

#### Scenario: Migration adds columns with no breaking changes

- GIVEN the current `pedidos_compra` table without OC columns
- WHEN the Alembic migration runs (`alembic upgrade head`)
- THEN the three columns MUST exist and MUST be NULL for all pre-existing rows
- AND existing pedidos MUST remain fully functional

#### Scenario: Partial fill is rejected at service layer

- GIVEN a request to link with only `oc_comp_id` and `oc_bra_id` supplied (missing `oc_poh_id`)
- WHEN the link service processes the request
- THEN it MUST raise HTTP 422 with detail `"oc_comp_id, oc_bra_id, and oc_poh_id must all be provided"`

---

### Requirement: REQ-OC-002 — OC candidate list filtered by supplier and status

**Priority:** must
**Type:** functional

`GET /administracion/compras/pedidos/{pedido_id}/oc-candidatas` MUST return only OCs that:

1. Belong to the same `supp_id` as the pedido's proveedor mapping.
2. Meet the "pending reception" criterion (the exact ERP field/condition is resolved by `sdd-design` — referred to as **CRITERION-PENDIENTE** throughout this spec). The design MUST document the chosen field and condition.
3. Are NOT the OC currently linked to this pedido (exclude it from candidates when re-linking).

Response shape per item (exact field names subject to design confirmation):

```json
{
  "comp_id": 1,
  "bra_id": 1,
  "poh_id": 12345,
  "numero_oc": "OC-2026-00042",
  "fecha_emision": "2026-05-10",
  "total": 150000.00,
  "moneda": "ARS",
  "estado_pendiente": "<value of CRITERION-PENDIENTE>"
}
```

#### Scenario: Only pending OCs for the correct supplier are returned

- GIVEN pedido `P1` linked to `proveedor_id=7` (mapped to `supp_id=42`)
- AND ERP has OCs for `supp_id=42`: OC #100 (pendiente), OC #101 (already received), OC #102 (pendiente, different supplier `supp_id=99`)
- WHEN `GET /administracion/compras/pedidos/P1/oc-candidatas` is called
- THEN response MUST contain only OC #100
- AND MUST NOT include OC #101 (not pending) nor OC #102 (wrong supplier)

#### Scenario: Currently linked OC is excluded from candidates

- GIVEN pedido `P1` already linked to OC #100
- WHEN `GET /administracion/compras/pedidos/P1/oc-candidatas` is called
- THEN response MUST NOT include OC #100

#### Scenario: No pending OCs for supplier returns empty list

- GIVEN pedido `P1` with `supp_id=42` and no pending OCs for that supplier in ERP
- WHEN `GET /administracion/compras/pedidos/P1/oc-candidatas` is called
- THEN response MUST be HTTP 200 with `{"items": []}`

---

### Requirement: REQ-OC-003 — Link OC (vincular)

**Priority:** must
**Type:** functional

`POST /administracion/compras/pedidos/{pedido_id}/vincular-oc`

Request body:
```json
{ "comp_id": 1, "bra_id": 1, "poh_id": 12345 }
```

Rules:
- The referenced OC (`comp_id`, `bra_id`, `poh_id`) MUST exist in `tb_purchase_order_header`.
- The OC MUST belong to the same `supp_id` as the pedido's proveedor.
- The OC MUST satisfy CRITERION-PENDIENTE.
- If the pedido already has a linked OC, the call MUST be rejected with HTTP 409 and detail `"Pedido already has a linked OC. Unlink first."`. Re-linking is desvincular + vincular, not a single overwrite call.
- On success: sets the three `oc_*` columns on the pedido.
- Response: the updated pedido summary (HTTP 200).

#### Scenario: Successful link

- GIVEN pedido `P1` with no linked OC, user has `gestionar_ordenes_compra`
- AND OC `(1,1,12345)` exists, belongs to `supp_id=42` (P1's supplier), and satisfies CRITERION-PENDIENTE
- WHEN `POST /vincular-oc` with `{comp_id:1, bra_id:1, poh_id:12345}`
- THEN HTTP 200, P1's `oc_comp_id=1, oc_bra_id=1, oc_poh_id=12345`

#### Scenario: OC does not exist → 404

- GIVEN OC `(1,1,99999)` does not exist in `tb_purchase_order_header`
- WHEN `POST /vincular-oc` with `{comp_id:1, bra_id:1, poh_id:99999}`
- THEN HTTP 404 with detail `"OC not found"`

#### Scenario: OC belongs to wrong supplier → 409

- GIVEN OC `(1,1,12345)` exists but belongs to `supp_id=99`, P1 maps to `supp_id=42`
- WHEN `POST /vincular-oc` with that OC
- THEN HTTP 409 with detail containing "supplier mismatch"

#### Scenario: Pedido already has OC → 409

- GIVEN P1 already linked to OC #100
- WHEN `POST /vincular-oc` with OC #200
- THEN HTTP 409 with detail `"Pedido already has a linked OC. Unlink first."`

#### Scenario: No permission → 403

- GIVEN user WITHOUT `administracion.gestionar_ordenes_compra`
- WHEN `POST /vincular-oc`
- THEN HTTP 403

#### Scenario: Pedido not found → 404

- GIVEN `pedido_id=9999` does not exist
- WHEN `POST /vincular-oc`
- THEN HTTP 404

---

### Requirement: REQ-OC-004 — Unlink OC (desvincular)

**Priority:** must
**Type:** functional

`DELETE /administracion/compras/pedidos/{pedido_id}/desvincular-oc`

Rules:
- If the pedido has NO linked OC, return HTTP 409 with detail `"Pedido has no linked OC"`.
- **If the pedido has confirmed ingresos** (any row in `pedido_compra_ingresos` for this `pedido_id`), the unlink MUST be **blocked**: HTTP 409, detail `"Cannot unlink OC: confirmed ingresos exist. Anular ingresos first."`.
- On success: sets `oc_comp_id=NULL, oc_bra_id=NULL, oc_poh_id=NULL`.
- Response: HTTP 204 No Content.

#### Scenario: Successful unlink (no ingresos)

- GIVEN P1 linked to OC #100, no rows in `pedido_compra_ingresos` for P1
- WHEN `DELETE /desvincular-oc`
- THEN HTTP 204, three columns set to NULL

#### Scenario: Unlink blocked by existing ingresos

- GIVEN P1 linked to OC #100, AND `pedido_compra_ingresos` has 2 rows for P1
- WHEN `DELETE /desvincular-oc`
- THEN HTTP 409 with detail `"Cannot unlink OC: confirmed ingresos exist. Anular ingresos first."`

#### Scenario: Pedido has no OC → 409

- GIVEN P1 has no linked OC
- WHEN `DELETE /desvincular-oc`
- THEN HTTP 409 with detail `"Pedido has no linked OC"`

#### Scenario: No permission → 403

- GIVEN user WITHOUT `administracion.gestionar_ordenes_compra`
- WHEN `DELETE /desvincular-oc`
- THEN HTTP 403

---

### Requirement: REQ-OC-005 — Re-link OC

**Priority:** must
**Type:** functional

Re-linking (switching from OC #100 to OC #200) is achieved by two sequential calls:
1. `DELETE /desvincular-oc` (must succeed: no ingresos)
2. `POST /vincular-oc` with the new OC

The system MUST NOT provide a single re-link endpoint. This is not a constraint: it is the explicit design.

#### Scenario: Re-link via desvincular + vincular

- GIVEN P1 linked to OC #100, no ingresos
- WHEN `DELETE /desvincular-oc` → HTTP 204
- AND `POST /vincular-oc` with `{comp_id:1, bra_id:1, poh_id:200}` → HTTP 200
- THEN P1 MUST have `oc_poh_id=200`

---

### Requirement: REQ-OC-006 — Per-depot breakdown (read-only)

**Priority:** must
**Type:** functional

`GET /administracion/compras/pedidos/{pedido_id}/orden-compra/detalle`

- MUST be called only when the pedido has a linked OC (HTTP 409 otherwise: `"Pedido has no linked OC"`).
- Reads from `tb_purchase_order_detail` JOIN `tb_storage` using the pedido's `(oc_comp_id, oc_bra_id, oc_poh_id)`.
- NEVER writes to ERP tables.

Response shape (array of lines):
```json
{
  "oc_comp_id": 1,
  "oc_bra_id": 1,
  "oc_poh_id": 12345,
  "lines": [
    {
      "pod_id": 1,
      "item_id": 5001,
      "item_descripcion": "Tornillo M8",
      "stor_id": 3,
      "deposito_nombre": "Depósito Central",
      "cantidad_oc": 100.0,
      "unidad": "UN"
    }
  ]
}
```

#### Scenario: Breakdown returns lines per depot

- GIVEN P1 linked to OC #12345 which has 3 lines: item A → depot 1, item A → depot 2, item B → depot 1
- WHEN `GET /orden-compra/detalle`
- THEN response MUST contain exactly 3 line entries with correct `stor_id`, `deposito_nombre`, `cantidad_oc`

#### Scenario: No linked OC → 409

- GIVEN P1 has no linked OC
- WHEN `GET /orden-compra/detalle`
- THEN HTTP 409 with detail `"Pedido has no linked OC"`

#### Scenario: ERP tables are not written

- GIVEN any call to this endpoint
- THEN NO INSERT, UPDATE, or DELETE SHALL be executed against `tb_purchase_order_header`, `tb_purchase_order_detail`, or `tb_storage`

---

## SLICE 2 — Confirmar Ingreso por Depósito

### Requirement: REQ-OC-007 — `pedido_compra_ingresos` table

**Priority:** must
**Type:** data-model

A new table `pedido_compra_ingresos` MUST be created with the following columns:

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | BigInteger | PK, auto-increment |
| `pedido_id` | BigInteger | FK `pedidos_compra.id`, NOT NULL, indexed |
| `oc_comp_id` | Integer | NOT NULL (snapshot from pedido at ingreso time) |
| `oc_bra_id` | Integer | NOT NULL |
| `oc_poh_id` | BigInteger | NOT NULL |
| `pod_id` | Integer | NOT NULL (line from `tb_purchase_order_detail`) |
| `item_id` | BigInteger | NOT NULL |
| `stor_id` | Integer | NOT NULL (depot receiving) |
| `cantidad_recibida` | Numeric(14,4) | NOT NULL, > 0 |
| `fecha_ingreso` | DateTime | NOT NULL, default UTC now |
| `usuario_id` | Integer | FK `usuarios.id`, NOT NULL |
| `observaciones` | String(500) | nullable |
| `created_at` | DateTime | NOT NULL, default UTC now |
| `updated_at` | DateTime | NOT NULL |

Indexes:
- `(pedido_id)` — for listing all ingresos of a pedido
- `(oc_comp_id, oc_bra_id, oc_poh_id, pod_id)` — for computing accumulated qty per OC line

No physical FK to ERP tables. `oc_*` columns and `pod_id` are stored as a snapshot (they reflect the OC at the moment of ingreso, independent of future ERP changes).

#### Scenario: Migration creates table

- GIVEN a clean DB with the Slice 1 migration applied
- WHEN the Slice 2 Alembic migration runs
- THEN `pedido_compra_ingresos` MUST exist with all columns and indexes described above

---

### Requirement: REQ-OC-008 — Confirm ingreso (partial / accumulated)

**Priority:** must
**Type:** functional

`POST /administracion/compras/pedidos/{pedido_id}/ingresos`

Request body (one or more lines):
```json
{
  "lines": [
    {
      "pod_id": 1,
      "item_id": 5001,
      "stor_id": 3,
      "cantidad_recibida": 50.0,
      "observaciones": "Primera entrega parcial"
    }
  ]
}
```

Rules:
- The pedido MUST have a linked OC. If not: HTTP 409 `"Pedido has no linked OC"`.
- Each `pod_id` MUST exist in `tb_purchase_order_detail` for the linked OC. If not: HTTP 422 `"pod_id {X} not found for linked OC"`.
- `cantidad_recibida` MUST be > 0. If not: HTTP 422.
- **Over-receipt rule**: for each line, the system MUST compute `saldo_pendiente = cantidad_oc - SUM(cantidad_recibida WHERE pedido_id=X AND pod_id=Y for ALL previous ingresos)`. If `cantidad_recibida` in the new request would cause `SUM > cantidad_oc`, the request MUST be rejected HTTP 409 with detail `"Over-receipt: pod_id {X} — saldo pendiente is {saldo}, requested {qty}"`.
- Multiple lines in a single request are processed atomically (all succeed or all fail).
- On success: inserts one row per line in `pedido_compra_ingresos`; returns HTTP 201 with the created ingreso IDs and updated `saldo_pendiente` per line.
- `usuario_id` is taken from the authenticated user (`get_current_user`), NOT from the request body.
- Permission: `administracion.gestionar_ordenes_compra`.

#### Scenario: Full receipt in one call

- GIVEN P1 linked to OC #12345, OC line pod_id=1 qty=100
- WHEN `POST /ingresos` with `{lines: [{pod_id:1, stor_id:3, cantidad_recibida:100}]}`
- THEN HTTP 201, one row created in `pedido_compra_ingresos` with `cantidad_recibida=100`
- AND `saldo_pendiente` for pod_id=1 MUST be 0

#### Scenario: Partial receipt accumulates correctly

- GIVEN P1 linked to OC #12345, pod_id=1 qty=100, no prior ingresos
- WHEN `POST /ingresos` with `cantidad_recibida=60` → HTTP 201
- AND `POST /ingresos` again with `cantidad_recibida=40` → HTTP 201
- THEN total `SUM(cantidad_recibida) WHERE pod_id=1` = 100
- AND `saldo_pendiente` for pod_id=1 = 0

#### Scenario: Over-receipt is rejected

- GIVEN P1 linked to OC #12345, pod_id=1 qty=100, prior ingreso of 80
- WHEN `POST /ingresos` with `cantidad_recibida=30`
- THEN HTTP 409 with detail `"Over-receipt: pod_id 1 — saldo pendiente is 20, requested 30"`

#### Scenario: Multiple lines in one request are atomic

- GIVEN P1 with OC lines pod_id=1 (qty=100, saldo=50) and pod_id=2 (qty=50, saldo=50)
- WHEN `POST /ingresos` with lines `[{pod_id:1, qty:50}, {pod_id:2, qty:60}]`
  (pod_id=2 over-receives by 10)
- THEN HTTP 409 for the whole request
- AND NO row MUST be inserted for either pod_id

#### Scenario: No linked OC → 409

- GIVEN P1 has no linked OC
- WHEN `POST /ingresos`
- THEN HTTP 409 `"Pedido has no linked OC"`

#### Scenario: No permission → 403

- GIVEN user WITHOUT `administracion.gestionar_ordenes_compra`
- WHEN `POST /ingresos`
- THEN HTTP 403

---

### Requirement: REQ-OC-009 — List ingresos

**Priority:** must
**Type:** functional

`GET /administracion/compras/pedidos/{pedido_id}/ingresos`

Response: list of confirmed ingresos for the pedido, including per-line `saldo_pendiente` computed as `cantidad_oc - SUM(cantidad_recibida)` for each `pod_id`.

Response shape:
```json
{
  "pedido_id": 1,
  "ingresos": [
    {
      "id": 1,
      "pod_id": 1,
      "item_id": 5001,
      "stor_id": 3,
      "deposito_nombre": "Depósito Central",
      "cantidad_recibida": 60.0,
      "fecha_ingreso": "2026-06-18T10:00:00Z",
      "usuario_nombre": "Ana García",
      "observaciones": null
    }
  ],
  "resumen_lineas": [
    {
      "pod_id": 1,
      "item_id": 5001,
      "cantidad_oc": 100.0,
      "cantidad_recibida_total": 60.0,
      "saldo_pendiente": 40.0
    }
  ]
}
```

#### Scenario: Empty ingresos list

- GIVEN P1 linked to OC #12345, no ingresos yet
- WHEN `GET /ingresos`
- THEN HTTP 200, `ingresos: []`, `resumen_lineas` MUST list all OC lines with `cantidad_recibida_total=0` and `saldo_pendiente=cantidad_oc`

#### Scenario: After partial ingreso

- GIVEN P1, OC pod_id=1 qty=100, one ingreso of 60
- WHEN `GET /ingresos`
- THEN `resumen_lineas[0].saldo_pendiente` MUST be 40.0

---

## Cross-Cutting Requirements

### Requirement: REQ-OC-010 — Permission gate

**Priority:** must
**Type:** security

ALL endpoints in this change (vincular, desvincular, oc-candidatas, detalle, ingresos GET+POST) MUST require `administracion.gestionar_ordenes_compra` via `PermisosService.tiene_permiso`. Any authenticated user without that permission MUST receive HTTP 403 before any DB operation is performed.

#### Scenario: Read-only breakdown requires permission

- GIVEN user WITHOUT `gestionar_ordenes_compra`
- WHEN `GET /orden-compra/detalle`
- THEN HTTP 403 (even though it is a read-only endpoint)

---

### Requirement: REQ-OC-011 — ERP tables are read-only

**Priority:** must
**Type:** non-functional

No endpoint or service in this change SHALL execute INSERT, UPDATE, or DELETE against `tb_purchase_order_header`, `tb_purchase_order_detail`, or `tb_storage`. This MUST be verifiable by a pytest test that mocks the DB session and asserts no write calls reach those tables.

---

### Requirement: REQ-OC-012 — Pedido not found → 404

**Priority:** must
**Type:** functional

For any endpoint using `{pedido_id}`, if the pedido does not exist the response MUST be HTTP 404 with detail `"Pedido not found"`. This check MUST run before permission checks against OC data.

---

## Edge Cases

### EC-01 — OC with lines in multiple depots

An OC can have multiple `tb_purchase_order_detail` rows for the same `item_id` with different `stor_id`. Each pod_id represents one line-depot combination. The breakdown MUST return all lines; ingreso confirmation operates per `pod_id`, not per `item_id`.

#### Scenario

- GIVEN OC #12345 with pod_id=1 (item A, depot 1, qty=40) and pod_id=2 (item A, depot 2, qty=60)
- WHEN `GET /orden-compra/detalle`
- THEN two separate lines in the response, one per `pod_id`, MUST NOT be collapsed

---

### EC-02 — Unlink when ingresos exist (spec rule: blocked)

Per REQ-OC-004: unlinking is BLOCKED if any ingreso exists. The user must manually address the existing ingresos first (the anulación workflow for ingresos is out of scope for these two slices and addressed in a future change). This spec documents the rule as a hard block; the design may add an `anular_ingreso` endpoint in a future change.

**Spec-level assumption**: no anulación endpoint is specified in this change. If the design determines one is needed to make unlinking unblocked, it should be flagged as a required addition before `sdd-tasks`.

---

### EC-03 — ERP data changes post-link

The ingreso record captures a snapshot of `(oc_comp_id, oc_bra_id, oc_poh_id, pod_id, item_id, stor_id)` at the moment of confirmation. If the OC is subsequently edited in the ERP (quantities, lines, depots change), existing ingreso records are NOT retroactively modified. The `GET /orden-compra/detalle` endpoint always reflects the current ERP mirror state, which may differ from the snapshot in `pedido_compra_ingresos`. This divergence is expected and not treated as an error.

---

### EC-04 — Re-link to a different OC

After desvincular (only possible if no ingresos exist per EC-02), the user may link any other valid OC. Existing ingresos are always scoped to the `pedido_id`, not to the specific OC identity. Since no ingresos can exist at desvincular time, there is no stale-ingreso risk on re-link.

---

## OPEN QUESTIONS

- **OPEN_QUESTION-OC-01 (CRITICAL):** The "pending reception" criterion (`CRITERION-PENDIENTE`) is not confirmed. `sdd-design` MUST inspect `tb_purchase_order_header` with real data and document the chosen field/condition before `sdd-tasks`. Until resolved, the spec refers to it abstractly.
- **OPEN_QUESTION-OC-02:** Is an `anular_ingreso` endpoint needed in Slice 2 to make EC-02 workable in practice, or is hard-blocking sufficient for the first delivery? Design to confirm.
- **OPEN_QUESTION-OC-03:** `saldo_pendiente` in the `GET /ingresos` response requires joining `tb_purchase_order_detail` for `cantidad_oc` at query time (read from live ERP mirror). If the OC line was deleted from the ERP after ingresos were recorded, `saldo_pendiente` cannot be computed. Design must address this edge case (use snapshot qty or handle NULL gracefully).
