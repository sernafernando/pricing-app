# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: ERP-missing OC block stays visible

Depósito MUST render one block per linked OC even when ERP lines are empty. The block MUST show the Spanish copy `OC no encontrada en ERP`. The system MUST NOT hide the OC section because the line list is empty.

#### Scenario: Empty ERP block is visible

- GIVEN P1 linked to OC-A with zero ERP lines
- WHEN Depósito opens P1
- THEN the OC-A block MUST be visible
- AND copy MUST include `OC no encontrada en ERP`

#### Scenario: Sibling blocks still render

- GIVEN P1 linked to OC-A (empty ERP) and OC-B (has lines)
- WHEN Depósito opens P1
- THEN both blocks MUST be visible
