# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Pedido tipo mercadería or servicio

`pedidos_compra` MUST have `tipo` ∈ {`mercaderia`, `servicio`}. Default MUST be `mercaderia`. A PM MAY set tipo on create. After create, only an admin MAY edit tipo. `servicio` MUST imply no OC (see `vincular-oc`).

#### Scenario: Default tipo on create

- GIVEN a PM creates a pedido without sending tipo
- WHEN the pedido is persisted
- THEN `tipo` MUST be `mercaderia`

#### Scenario: Admin can edit tipo; PM cannot after create

- GIVEN an existing pedido created by PM U
- WHEN U PATCHes `tipo` to `servicio`
- THEN the system MUST reject the edit
- WHEN an admin PATCHes `tipo` to `servicio`
- THEN `tipo` MUST become `servicio`

### Requirement: Pedido responsable

`pedidos_compra` MUST have `responsable_id`. On create it MUST default to `created_by`. Existing rows MUST backfill `responsable_id = created_by`. Editors MUST be admin or the pedido creator only.

#### Scenario: Default and backfill to creator

- GIVEN a new pedido created by user C, and a legacy row with null responsable
- WHEN create and backfill run
- THEN both MUST have `responsable_id = C` / `created_by`

#### Scenario: Non-editor cannot change responsable

- GIVEN pedido created by C, actor U is neither admin nor C
- WHEN U changes `responsable_id`
- THEN the system MUST reject the change

### Requirement: Visibility chips OC, factura, Match

The Pedidos list MUST show three chips, not procesal states: OC vinculada, factura cargada (normalized rows), OC Match status. Procesal values MUST NOT embed sin/con OC.

#### Scenario: Chips independent of procesal

- GIVEN a pedido with one OC, one factura row, and Match done
- WHEN the Pedidos list renders
- THEN OC, factura, and Match chips MUST be visible
- AND the procesal value MUST NOT be a sin-OC or con-OC label

### Requirement: Procesal axis on Pedidos

Pedidos MUST expose a procesal axis separate from financial `estado`: `n_a_servicio` | `por_recibir` | `recibido` | `faltantes_sin_res` | `faltantes_con_res` | `controlado`. Servicio MUST show `n_a_servicio`. Pedidos list MUST show logistic/procesal states. The `aprobado` badge MUST NOT be renamed Pendiente.

#### Scenario: Servicio is n_a_servicio

- GIVEN `tipo=servicio`
- WHEN procesal is evaluated
- THEN it MUST be `n_a_servicio`
- AND the Pedidos list MUST show that logistic state

#### Scenario: Mercadería waiting for goods

- GIVEN `tipo=mercaderia` financially pagado and not yet arrived
- WHEN procesal is evaluated
- THEN it MUST be `por_recibir`
