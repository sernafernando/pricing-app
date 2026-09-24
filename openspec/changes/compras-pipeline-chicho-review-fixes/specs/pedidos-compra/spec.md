# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Optional read-path seed for legacy text-only pedidos

When chips or list visibility evaluate a pedido that has nonempty `facturas_documento` tokens and zero factura rows, the system MAY seed rows from those tokens using the same ≤100-character, casefold-dedupe, and UNIQUE `(pedido_id, numero)` rules as migrate. Pedidos that already have factura rows MUST NOT be re-seeded. Seeded rows MUST be constancia (`cargada` false). Seed MUST NOT turn the factura-cargada chip on.

(Design D-READ-SEED: do **not** seed on chips/GET in apply unless an explicit backfill is invoked. The MAY is leftover optionality; apply MUST NOT introduce GET side effects.)

#### Scenario: Legacy text-only becomes constancia, not cargada

- GIVEN a pedido with `facturas_documento` = `FA-10` and zero factura rows
- WHEN an explicit seed/backfill runs
- THEN a factura row for `FA-10` MAY be seeded
- AND if seeded, `cargada` MUST be false
- AND the factura-cargada chip MUST stay off

#### Scenario: Existing rows are not re-seeded

- GIVEN a pedido that already has a factura row
- WHEN chips or list visibility are evaluated
- THEN no extra factura row MUST be inserted

### Requirement: Has-number vs cargada are distinct

The system MUST distinguish “has a factura document number” (constancia: ≥1 `pedido_factura_documentos` row) from “factura cargada” (ERP check: ≥1 row with `cargada=true`). Detalle MUST list each factura number with a checkbox for the ERP check. The list chip “Factura” / “Factura cargada” MUST follow cargada flags only. NV / `pedidos_documento` MUST remain text constancia without a cargada checkbox.

#### Scenario: Numbers without check do not light the cargada chip

- GIVEN a pedido with row `FA-10` unchecked
- WHEN the Pedidos list and detalle render
- THEN the factura-cargada chip MUST be off
- AND detalle MUST still show number `FA-10` as constancia
- AND detalle MUST show an unchecked ERP checkbox for that row

#### Scenario: Check lights the cargada chip

- GIVEN the same pedido
- WHEN Administración checks `FA-10` cargada
- THEN the factura-cargada chip MUST be on
- AND the checkbox MUST be checked

## MODIFIED Requirements

### Requirement: Visibility chips OC, factura, Match

The Pedidos list MUST show three chips, not procesal states: OC vinculada, factura cargada (ERP check), OC Match status. Procesal values MUST NOT embed sin/con OC. Factura-cargada MUST follow `pedido_factura_documentos.cargada`, **not** mere row presence, **not** Match tokens, **not** ERP `ct_transaction`. A Match token or constancia row without `cargada` MUST leave the factura-cargada chip off.

(Previously in this change: chips were row-based and Match writeback turned the factura chip on. Gabe 2026-09-23: chip = ERP check.)

#### Scenario: Chips independent of procesal

- GIVEN a pedido with one OC, one factura row marked cargada, and Match done
- WHEN the Pedidos list renders
- THEN OC, factura, and Match chips MUST be visible
- AND the procesal value MUST NOT be a sin-OC or con-OC label

#### Scenario: Match writeback does not turn factura-cargada chip on

- GIVEN a pedido with zero factura rows
- WHEN OC Match writeback persists a factura number
- THEN a constancia row MUST exist
- AND the factura-cargada chip MUST stay off
- AND a false falta-factura chip state MUST NOT appear
