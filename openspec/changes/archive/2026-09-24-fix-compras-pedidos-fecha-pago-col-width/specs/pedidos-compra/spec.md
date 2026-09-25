# Delta for pedidos-compra

## ADDED Requirements

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
