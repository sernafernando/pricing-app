# Delta for vincular-oc

## ADDED Requirements

### Requirement: Pedido detail OC table shows código and description

Pedido detail Orden de compra ERP breakdown MUST show columns **Código**, **Descripción**, **Qty OC**, and **Saldo pendiente**. Código MUST be `productos_erp.codigo` when available. Descripción MUST be the product description (`item_nombre`) with ellipsis when truncated. The table MUST NOT use Item ID or Depósito as column headers. Qty OC and Saldo pendiente headers and values MUST be centered.

#### Scenario: Description and código visible

- GIVEN a linked OC line with `item_nombre` and `item_code`
- WHEN pedido detail renders the OC breakdown
- THEN the description MUST appear
- AND the código MUST appear
- AND the headers MUST NOT be Item ID or Depósito

#### Scenario: Qty and saldo centered

- GIVEN the OC breakdown table
- WHEN headers Qty OC and Saldo pendiente render
- THEN those headers and their cell values MUST be center-aligned

### Requirement: Pedido detail stacks one table per linked OC

When a pedido has more than one linked OC, detail MUST render one breakdown table per OC, stacked, each titled with that OC’s `oc_poh_id`. When there is one OC, one table MUST remain.

#### Scenario: Two linked OCs show two tables

- GIVEN a pedido linked to OC `#100` and OC `#200` with lines on each
- WHEN pedido detail loads OC detalle
- THEN a block for `#100` and a block for `#200` MUST appear
- AND each block MUST list only that OC’s lines
