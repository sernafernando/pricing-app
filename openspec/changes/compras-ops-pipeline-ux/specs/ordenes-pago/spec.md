# Delta for ordenes-pago

## ADDED Requirements

### Requirement: OPs column lists all linked Pricing P-numbers

The Órdenes de Pago list MUST show a column of every Pricing pedido number (`P-…`) linked to that OP via imputations. The column MUST list all linked numbers, not a single one. It MUST NOT substitute `pedidos_documento` or ERP doc numbers.

#### Scenario: Multiple linked pedidos appear

- GIVEN OP-1 imputes to pedidos `P-01-2026-00001` and `P-01-2026-00002`
- WHEN the OPs list renders
- THEN the pedidos column MUST show both `P-01-2026-00001` and `P-01-2026-00002`

#### Scenario: OP with no pedido imputations

- GIVEN an OP in `a_cuenta` with no pedido imputations
- WHEN the OPs list renders
- THEN the pedidos column MUST be empty (no placeholder P-number)
