# Delta for pedidos-compra

## ADDED Requirements

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
