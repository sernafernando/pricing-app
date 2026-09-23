# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Optional read-path seed for legacy text-only pedidos

When chips or list visibility evaluate a pedido that has nonempty `facturas_documento` tokens and zero factura rows, the system MAY seed rows from those tokens using the same ≤100-character, casefold-dedupe, and UNIQUE `(pedido_id, numero)` rules as migrate. Pedidos that already have factura rows MUST NOT be re-seeded.

#### Scenario: Legacy text-only becomes cargada

- GIVEN a pedido with `facturas_documento` = `FA-10` and zero factura rows
- WHEN chips or list visibility are evaluated
- THEN a factura row for `FA-10` MAY be seeded
- AND if seeded, the factura chip MUST be on

#### Scenario: Existing rows are not re-seeded

- GIVEN a pedido that already has a factura row
- WHEN chips or list visibility are evaluated
- THEN no extra factura row MUST be inserted

## MODIFIED Requirements

### Requirement: Visibility chips OC, factura, Match

The Pedidos list MUST show three chips, not procesal states: OC vinculada, factura cargada (normalized rows), OC Match status. Procesal values MUST NOT embed sin/con OC. Factura-cargada MUST follow `pedido_factura_documentos` rows, including rows inserted by OC Match writeback. A Match token without a row MUST NOT leave the factura chip off.

(Previously: chips were row-based but Match writeback did not create a row, so the factura chip stayed off.)

#### Scenario: Chips independent of procesal

- GIVEN a pedido with one OC, one factura row, and Match done
- WHEN the Pedidos list renders
- THEN OC, factura, and Match chips MUST be visible
- AND the procesal value MUST NOT be a sin-OC or con-OC label

#### Scenario: Match writeback turns factura chip on

- GIVEN a pedido with zero factura rows
- WHEN OC Match writeback persists a factura number
- THEN the factura chip MUST be on
- AND a false falta-factura chip state MUST NOT appear
