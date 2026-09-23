# Delta for vincular-oc

## ADDED Requirements

### Requirement: N OC blocks on one pedido

Depósito MUST render one block per linked OC on a single pedido. Blocks MUST be unlimited. Adding an OC MUST NOT replace existing links.

#### Scenario: Two OCs render two blocks

- GIVEN P1 linked to OC-A and OC-B
- WHEN Depósito opens P1
- THEN exactly two OC blocks MUST appear
- AND each block MUST bind only that OC’s lines

### Requirement: Servicio forbids OC

When `tipo=servicio`, candidate list MUST be empty and `POST /vincular-oc` MUST return HTTP 409. Existing mercadería links are unchanged.

#### Scenario: Vincular rejected on servicio

- GIVEN P1.tipo = `servicio`
- WHEN `POST /vincular-oc` is called
- THEN HTTP 409
- AND no OC MUST be linked

## MODIFIED Requirements

### Requirement: REQ-OC-001 — Three nullable link columns on `pedidos_compra`

The system MUST persist one or more complete OC identities per pedido. Each identity is a triple:

| Column | Type | Description |
|--------|------|-------------|
| `oc_comp_id` | Integer, nullable | Logical FK to `tb_purchase_order_header.comp_id` |
| `oc_bra_id` | Integer, nullable | Logical FK to `tb_purchase_order_header.bra_id` |
| `oc_poh_id` | BigInteger, nullable | Logical FK to `tb_purchase_order_header.poh_id` |

Rules:
- Each triple is ALL NULL (unused slot) or ALL NOT NULL (linked). A partially-filled triple is invalid.
- A pedido MAY have unlimited triples. Zero triples means unlinked.
- No physical FK constraint against the ERP mirror (same pattern as `ct_transaction_id`).
- A partial index on linked `oc_poh_id` MUST exist.
- Existing single-triple rows MUST remain valid after migrate.

(Previously: exactly one triple of three columns on `pedidos_compra`; a second link was impossible.)

#### Scenario: Migration adds columns with no breaking changes

- GIVEN the current `pedidos_compra` table without OC columns
- WHEN the Alembic migration runs (`alembic upgrade head`)
- THEN the three columns MUST exist and MUST be NULL for all pre-existing rows
- AND existing pedidos MUST remain fully functional

#### Scenario: Partial fill is rejected at service layer

- GIVEN a request to link with only `oc_comp_id` and `oc_bra_id` supplied (missing `oc_poh_id`)
- WHEN the link service processes the request
- THEN it MUST raise HTTP 422 with detail `"oc_comp_id, oc_bra_id, and oc_poh_id must all be provided"`

#### Scenario: Second triple is stored without clearing the first

- GIVEN P1 already linked to OC triple (1,1,100)
- WHEN a second complete triple (1,1,200) is persisted
- THEN both triples MUST remain linked to P1

### Requirement: REQ-OC-003 — Link OC (vincular)

`POST /administracion/compras/pedidos/{pedido_id}/vincular-oc`

Request body:
```json
{ "comp_id": 1, "bra_id": 1, "poh_id": 12345 }
```

Rules:
- The referenced OC (`comp_id`, `bra_id`, `poh_id`) MUST exist in `tb_purchase_order_header`.
- The OC MUST belong to the same `supp_id` as the pedido's proveedor.
- The OC MUST satisfy CRITERION-PENDIENTE.
- The pedido MUST have `tipo=mercaderia`. `servicio` MUST be HTTP 409.
- If the pedido already has linked OCs, the call MUST add the new OC without replacing existing links. Duplicate of an already-linked triple MUST be HTTP 409.
- On success: persists the new triple on the pedido.
- Response: the updated pedido summary (HTTP 200).

(Previously: a second `POST /vincular-oc` returned 409 `"Pedido already has a linked OC. Unlink first."`.)

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

#### Scenario: Pedido already has OC → adds without replace

- GIVEN P1 already linked to OC #100
- WHEN `POST /vincular-oc` with OC #200
- THEN HTTP 200
- AND both OC #100 and OC #200 MUST remain linked
- AND OC #100 MUST NOT be replaced

#### Scenario: No permission → 403

- GIVEN user WITHOUT `administracion.gestionar_ordenes_compra`
- WHEN `POST /vincular-oc`
- THEN HTTP 403

#### Scenario: Pedido not found → 404

- GIVEN `pedido_id=9999` does not exist
- WHEN `POST /vincular-oc`
- THEN HTTP 404

#### Scenario: Duplicate triple rejected

- GIVEN P1 already linked to OC `(1,1,12345)`
- WHEN `POST /vincular-oc` with the same triple
- THEN HTTP 409
- AND the existing link MUST remain
