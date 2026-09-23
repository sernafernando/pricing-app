# Delta for pedidos-compra

## ADDED Requirements

### Requirement: faltantes_con_res display label

The Pedidos list MUST label `eje_procesal=faltantes_con_res` as “Faltantes con resolución”.

#### Scenario: Resolved faltantes label

- GIVEN P with eje `faltantes_con_res`
- WHEN the Pedidos list renders
- THEN the procesal label MUST be “Faltantes con resolución”

### Requirement: OC chip is vinculación

The Pedidos OC chip MUST mean OC vinculación (header / `ocs[]`), not GBP existence. When `ocs.length > 1`, the list MUST also show compact per-OC labels (`#{poh}`). A single OC MUST keep the chip only.

#### Scenario: Chip stays vinculación

- GIVEN P linked in Pricing but missing in ERP
- WHEN the Pedidos list renders
- THEN the OC chip MUST still appear as vinculación
- AND a separate “exists in GBP” chip MUST NOT appear

#### Scenario: Multi-OC compact labels

- GIVEN P with `ocs` of two poh ids 100 and 200
- WHEN the Pedidos list renders
- THEN the OC chip MUST appear
- AND compact labels `#100` and `#200` MUST appear

#### Scenario: Single OC chip only

- GIVEN P with exactly one OC
- WHEN the Pedidos list renders
- THEN the OC chip MUST appear
- AND extra per-OC labels MUST NOT appear

## MODIFIED Requirements

### Requirement: Pedido tipo mercadería or servicio

`pedidos_compra` MUST have `tipo` ∈ {`mercaderia`, `servicio`}. Default MUST be `mercaderia`. A PM MAY set tipo on create (create form selector). After create, only an admin MAY edit tipo. `servicio` MUST imply no OC (see `vincular-oc`).

(Previously: PM MAY set tipo on create was specified, but the create form did not expose a selector.)

#### Scenario: Default tipo on create

- GIVEN a PM creates a pedido without sending tipo
- WHEN the pedido is persisted
- THEN `tipo` MUST be `mercaderia`

#### Scenario: PM sets tipo on create

- GIVEN a PM create form
- WHEN the PM selects `servicio` and submits
- THEN persisted `tipo` MUST be `servicio`

#### Scenario: Admin can edit tipo; PM cannot after create

- GIVEN an existing pedido created by PM U
- WHEN U PATCHes `tipo` to `servicio`
- THEN the system MUST reject the edit
- WHEN an admin PATCHes `tipo` to `servicio`
- THEN `tipo` MUST become `servicio`
