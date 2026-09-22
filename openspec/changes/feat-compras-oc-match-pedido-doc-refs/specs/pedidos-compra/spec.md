# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Documentary Factura/s and Pedido/s columns

`pedidos_compra` MUST add nullable Text columns `facturas_documento` and `pedidos_documento`. They MUST NOT replace `numero` or `numero_factura`. This change MUST NOT add an index on either column.

#### Scenario: New columns are nullable Text

- GIVEN an existing pedido without supplier document numbers
- WHEN the schema is applied
- THEN `facturas_documento` and `pedidos_documento` are null
- AND `numero` and `numero_factura` remain unchanged

### Requirement: Operator-editable metadata like observaciones

Both columns MUST be operator-editable on the same pedido create/update APIs as `observaciones`, including both draft and approved editable sets. Operator PUT MUST accept a full replacement string; that MUST be the only wipe path. Null-ignored clear semantics MUST match `observaciones`. Cosmetic `/corregir` MUST inherit both columns and MUST NOT treat them as financial.

#### Scenario: PUT replaces the stored string

- GIVEN a pedido whose `facturas_documento` is `A; B`
- WHEN an operator PUT sends `facturas_documento=C`
- THEN the stored value becomes `C`
- AND `match_forward` is not invoked

#### Scenario: Corregir inherits both columns

- GIVEN a pedido with both documentary fields set
- WHEN `/corregir` clones it
- THEN the clone copies `facturas_documento` and `pedidos_documento`
- AND financial correccion rules are unchanged

### Requirement: API expose and pedido-form fields

Create, update, and response schemas MUST expose both columns. Pedido forms MUST show labels **Factura/s** and **Pedido/s** on `ModalPedidoCompra`, `ModalPedidoDetalle`, and `ModalCorregirPedido`. Pedido list columns and reception chips MUST stay out of scope.

#### Scenario: Forms send and display both fields

- GIVEN a pedido with `facturas_documento=0001-99` and `pedidos_documento=PED-184465`
- WHEN the operator opens create, detail, or corregir
- THEN Factura/s and Pedido/s show the stored strings
- AND create/update persist the submitted values

#### Scenario: Empty detail shows dash

- GIVEN both columns are null
- WHEN detalle renders
- THEN each field shows "—"
