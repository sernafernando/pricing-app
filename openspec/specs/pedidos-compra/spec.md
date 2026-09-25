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

### Requirement: Fecha pago column is date-sized

On the Pedidos list table, the **Fecha pago** column MUST be sized for a `dd/mm/yyyy` date (`##/##/####`), not for a date-plus-badge on one row. The column width MUST be `110px` (within the 100–110px product range). An urgency badge (Clock + `Nd` / `Hoy` / `Vencido Nd`) MAY wrap onto the next line under the date. The column MUST NOT be wide enough that **Proveedor** and **Mon.** overlap. **Estado** and **Proceso** column widths MUST NOT increase.

#### Scenario: Fecha pago col is 110px

- GIVEN the Pedidos table columns are rendered
- WHEN the Fecha pago `<col>` is measured
- THEN its width MUST be `110px`
- AND Estado MUST remain `152px`
- AND Proceso MUST remain `220px`

#### Scenario: Urgency badge may wrap under the date

- GIVEN an `aprobado` pedido whose estimated pay date is within 7 days
- WHEN the Fecha pago cell renders the date and urgency badge
- THEN the date MUST remain `dd/mm/yyyy`
- AND the badge MAY wrap below the date instead of widening the column

#### Scenario: Proveedor and Mon. do not collide

- GIVEN a Pedidos row with a non-empty proveedor name and a moneda value
- WHEN the table row renders
- THEN Proveedor text and the Mon. cell MUST NOT overlap

### Requirement: Empresa name is two-line centered without ellipsis

On the Pedidos list, **Empresa** MUST show `empresa_nombre` (fallback `#id`). The same wrap-and-clip rule MUST apply to every name: wrap on at most two centered lines, then clip. The cell MUST NOT use ellipsis or `text-overflow: ellipsis`. A short name MUST stay on one line when it fits the existing Empresa column. A longer name MUST wrap (on spaces, or anywhere if a token does not fit) and MUST clip after two lines. The cell MUST NOT overflow into **Proveedor**. Column widths MUST stay as they are. The UI MUST NOT special-case any company name.

(Previously: required full visibility of hardcoded worst-case names Grupo Gauss and Pastoriza, width capped to those names, and MUST NOT clip.)

#### Scenario: Two-word name wraps on the space

- GIVEN a pedido whose empresa name has two words that do not fit one line
- WHEN the Pedidos Empresa cell renders
- THEN the painted text MUST include both words
- AND the cell content MUST be horizontally centered
- AND the name MUST occupy at most two lines

#### Scenario: Short name stays one line when it fits

- GIVEN a pedido whose empresa name fits the existing Empresa column on one line
- WHEN the Pedidos Empresa cell renders
- THEN the full name MUST appear on one centered line
- AND MUST NOT be truncated with ellipsis

#### Scenario: Long name clips after two lines without overflowing

- GIVEN a pedido whose empresa name exceeds two lines in the existing Empresa column
- WHEN the Pedidos Empresa cell renders
- THEN the cell MUST clip after two centered lines
- AND MUST NOT show ellipsis
- AND MUST NOT paint over the Proveedor cell

#### Scenario: Wrap rule is name-agnostic

- GIVEN two pedidos with different empresa names
- WHEN both Empresa cells render
- THEN both MUST use the same wrap-and-clip rule
- AND neither cell MUST depend on a particular company name

### Requirement: Acciones icons use a two-by-two grid

Pedidos **Acciones** MUST lay out icon buttons in a CSS grid of **two columns** (2×2 when four icons show). Extra icons MAY add rows. The Acciones column MUST be narrower than the current one-row ~180px layout.

#### Scenario: Four icons occupy two columns

- GIVEN a row that shows four action icons
- WHEN the Acciones cell renders
- THEN the icons MUST occupy two columns, not four in one row
- AND the Acciones `<col>` width MUST be less than `180px`

### Requirement: Pedidos column budget fits 1280–1400

Fixed Pedidos columns MUST leave leftover width for **Proveedor** at ~1280–1400 useful table width. **Fecha pago** MUST stay `110px`, **Mon.** `60px`, **Estado** `152px`, **Proceso** `220px` unless a measured cut is recorded in this change’s design. Número, Empresa, Saldo, Plazo, and Acciones MUST stay width-capped. Proveedor MUST remain the only flexible absorber. Proveedor text and **Mon.** MUST NOT overlap.

#### Scenario: No Proveedor/Mon collision at 1280–1400

- GIVEN a Pedidos row with a long proveedor name and a moneda value
- WHEN the table is painted at 1280–1400px useful width
- THEN Proveedor ink and the Mon. cell MUST have positive width
- AND their overlap area MUST be 0

#### Scenario: Locked columns stay

- GIVEN Pedidos columns are rendered
- WHEN `<col>` widths are read
- THEN Fecha pago MUST be `110px`
- AND Mon. MUST be `60px`
- AND Estado MUST be `152px`
- AND Proceso MUST be `220px`
