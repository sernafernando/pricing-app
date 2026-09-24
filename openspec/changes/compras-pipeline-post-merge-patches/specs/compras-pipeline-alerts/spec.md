# Delta for compras-pipeline-alerts

## ADDED Requirements

### Requirement: Banner and Ver force-open pedido detalle

Banner and Ver MUST open pedido detalle even when the current URL already contains the same `?pedido=`. Close or Compras tab change MUST NOT leave a stale query that reopens detalle. Inbound notification land MUST still open once.

#### Scenario: Banner force-opens if URL already has pedido

- GIVEN the operator is on Pedidos at `?pedido=12` with detalle closed
- WHEN the operator activates the banner for pedido 12
- THEN detalle for 12 MUST open

#### Scenario: Close or tab change does not stale-reopen

- GIVEN detalle opened from a banner
- WHEN the operator closes detalle or switches Compras tab
- THEN `?pedido=` / `focus` MUST be cleared or remount-safe
- AND returning to Pedidos MUST NOT reopen that pedido

#### Scenario: Inbound land still opens once

- GIVEN a notification deep-link with `?pedido=12`
- WHEN the operator lands on Compras Pedidos
- THEN detalle for 12 MUST open once
- AND that land MUST NOT be treated as a stale leftover query

### Requirement: Checkbox tracks persisted factura cargada

The factura-cargada checkbox MUST reflect the persisted `cargada` flag on the factura row. The 5-minute factura-cargada timer and PM notify sweep MUST stay unchanged. Constancia-only rows, including NC/ND that MUST NOT become factura rows, MUST render unchecked.

#### Scenario: Checkbox follows persisted cargada

- GIVEN a factura row with persisted `cargada=false`
- WHEN detalle renders
- THEN the ERP checkbox MUST be unchecked
- AND MUST NOT appear stuck checked

#### Scenario: Checked row stays checked after persist

- GIVEN a factura row with persisted `cargada=true`
- WHEN detalle re-renders
- THEN the ERP checkbox MUST stay checked

#### Scenario: Timer and PM notify unchanged

- GIVEN Administración checks `cargada` at T0
- WHEN the sweep runs before 5 minutes
- THEN no factura-cargada notification MUST fire
- AND at T0 + 5 minutes the existing recipient sweep MUST still fire
