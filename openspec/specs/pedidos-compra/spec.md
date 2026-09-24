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


### Requirement: Pedidos default excludes only cancelado

The Pedidos list default MUST include every estado except `cancelado`. `cancelado` MUST remain selectable. The estado dropdown MUST also offer `recibido`, `con_faltantes`, and `controlado`.

| Filter | Included |
|---|---|
| Default | all estados except `cancelado` |
| Explicit `cancelado` | cancelado rows only |
| Logistic extras | `recibido`, `con_faltantes`, `controlado` selectable |

#### Scenario: Default hides cancelado only

- GIVEN pedidos in `aprobado`, `pagado`, and `cancelado`
- WHEN Pedidos loads with the default filter
- THEN `aprobado` and `pagado` MUST appear
- AND `cancelado` MUST NOT

#### Scenario: Cancelado is selectable

- GIVEN the same pedidos
- WHEN the operator selects `cancelado`
- THEN only cancelado rows MUST appear

#### Scenario: Logistic estados are selectable

- GIVEN pedidos in `recibido`, `con_faltantes`, and `controlado`
- WHEN the operator selects each of those dropdown values
- THEN only matching rows MUST appear

### Requirement: Pedido query is consumed then cleared

Closing pedido detalle or changing the Compras tab MUST clear or remount-safe `?pedido=` and `focus`. Inbound land MUST open once, then consume the query. Ver MUST force-open detalle even when the URL already has the same `?pedido=`.

#### Scenario: Close clears query so remount does not reopen

- GIVEN detalle open from `?pedido=12`
- WHEN the operator closes detalle
- THEN `?pedido=` / `focus` MUST be cleared
- AND remounting Pedidos MUST NOT reopen pedido 12

#### Scenario: Tab change does not sticky-reopen

- GIVEN detalle opened from a banner onto Pedidos
- WHEN the operator switches to another Compras tab and returns to Pedidos
- THEN pedido detalle MUST stay closed

#### Scenario: Ver force-opens the same URL

- GIVEN Pedidos already at `?pedido=12` with detalle closed
- WHEN the operator activates Ver for pedido 12
- THEN detalle for 12 MUST open

### Requirement: Proceso chips use semantic colors

In the Pedidos **Proceso** column, chips MUST use distinct semantic tones (not a single gray/white for all). Minimum mapping:

| Chip | Tone |
|---|---|
| OC | info/blue |
| Factura (cargada) | success/green |
| Match error | error/red |
| Match other statuses | warning or info (not gray-identical to OC) |
| Eje procesal badges (incl. recibido / con faltantes ejes) | warning/orange or success per eje — visibly stronger than muted |
| Número (constancia only) | MAY stay muted/dashed |

Use existing design tokens (`--cf-accent-*`, `--success`, `--error`, etc.) — no hardcoded hex outside tokens.

#### Scenario: Factura and Match error are not gray twins

- GIVEN a row with `factura_cargada` and `oc_match_status=error`
- WHEN the Proceso cell renders
- THEN the Factura chip and Match error chip MUST use different non-neutral colors
- AND neither MUST look identical to the default gray `.chip` baseline

#### Scenario: OC chip is distinctly colored

- GIVEN a row with OC vinculada
- WHEN the Proceso cell renders
- THEN the OC chip MUST use an info/blue tone distinct from muted Número

### Requirement: Con faltantes estado is not clipped by Proceso

The Estado column badge for `con_faltantes` ("Con faltantes") MUST remain fully visible and MUST NOT render underneath or behind the Proceso column (no z-index/overflow clip that hides the badge under Proceso).

#### Scenario: Con faltantes badge stays readable beside Proceso

- GIVEN a pedido with `estado=con_faltantes` and proceso chips present
- WHEN the Pedidos table row renders
- THEN the "Con faltantes" estado badge MUST be fully visible
- AND MUST NOT be covered by the Proceso cell content
