# compras-factura-documentos Specification

## Purpose

Invoice “cargada” is normalized document rows (option A), not ERP `ct_transaction` multi-link. Seed from existing `facturas_documento` tokens. ERP multi-factura stays deprecated and untouched.

## Requirements

### Requirement: Normalized factura rows (option A)

The system MUST persist each loaded invoice as a normalized row on the pedido. “Factura cargada” MUST mean the pedido has at least one such row. The system MUST NOT treat ERP multi-link / `ct_transaction` matching as cargada.

#### Scenario: Row makes factura cargada

- GIVEN a pedido with zero factura rows
- WHEN an operator adds a row with a nonempty document number
- THEN the pedido MUST be factura cargada
- AND the OC/factura/Match chips MUST show factura cargada

#### Scenario: ERP multi-link is not cargada

- GIVEN a pedido that has ERP `ct_transaction` links but zero factura rows
- WHEN the list evaluates cargada
- THEN factura MUST NOT be cargada
- AND no ERP multi-link write MUST occur

### Requirement: Seed from facturas_documento tokens

On migrate/backfill the system MUST seed rows by splitting existing `facturas_documento` on `;` tokens, trimming empties. The raw `facturas_documento` field MUST remain. `pedidos_documento` MUST stay write-once and MUST NOT be used as factura identity.

#### Scenario: Semicolon tokens become rows

- GIVEN `facturas_documento` = `A-1; A-2; ;A-3`
- WHEN seed runs
- THEN three rows MUST exist with numbers `A-1`, `A-2`, `A-3`
- AND `facturas_documento` MUST stay unchanged

#### Scenario: Empty token field seeds nothing

- GIVEN `facturas_documento` is null or only separators
- WHEN seed runs
- THEN the pedido MUST have zero factura rows

### Requirement: Nonempty document number

Each row MUST have a nonempty document number after trim. Create/update with empty number MUST be rejected (HTTP 422). Alert fan-out MUST NOT fire without a nonempty number.

#### Scenario: Empty number rejected

- GIVEN an operator submits a factura row with number `""` or whitespace
- WHEN save is attempted
- THEN the system MUST reject with HTTP 422
- AND no row MUST persist
- AND no factura alert MUST be created

### Requirement: Five-minute undo by marker

Removing a just-added row MUST be allowed for 5 minutes from the row’s create marker. After the window, undo MUST be rejected. Undo MUST retract in-app factura alerts for that row.

#### Scenario: Undo inside five minutes

- GIVEN a row created 2 minutes ago
- WHEN the operator undoes that load
- THEN the row MUST be removed
- AND factura cargada MUST clear if no rows remain
- AND that row’s alerts MUST be retracted

#### Scenario: Undo after five minutes rejected

- GIVEN a row created 6 minutes ago
- WHEN the operator undoes that load
- THEN the system MUST reject the undo
- AND the row MUST remain
