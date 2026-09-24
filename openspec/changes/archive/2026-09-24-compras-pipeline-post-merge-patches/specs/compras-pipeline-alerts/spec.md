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

### Requirement: Factura banner Ver and X dismiss permanently

For `compras.factura_cargada` (and other non-faltantes compras banners that use `/ok` today), **X** and **Ver** MUST both dismiss permanently via `PATCH /notificaciones/{id}/ok`. Ver MUST `/ok` then navigate. Refresh MUST NOT bring that notification back after Ver or X.

#### Scenario: Ver on factura banner dismisses permanently

- GIVEN an unread `compras.factura_cargada` banner
- WHEN the operator presses **Ver**
- THEN the client MUST `PATCH .../ok`
- AND the banner MUST leave the stack
- AND navigation to the pedido deep-link MUST run
- AND a full refresh MUST NOT show that notification again

#### Scenario: X on factura banner dismisses permanently

- GIVEN an unread `compras.factura_cargada` banner
- WHEN the operator presses **X**
- THEN the client MUST `PATCH .../ok`
- AND the banner MUST leave the stack

### Requirement: Faltantes banner closable with X (snooze), not permanent via Ver

`compras.faltantes` banners MUST be closable with **X**. X MUST behave like **Posponer**: `PATCH .../snooze` (hide ~1 hour; returns if still unresolved). That snooze window MUST NOT change.

**Ver** on faltantes MUST navigate only — MUST NOT call `/ok` and MUST NOT snooze.

Permanent clear of faltantes MUST remain the resolution path (responsable texto → faltantes resueltos), unchanged.

#### Scenario: Faltantes shows X and X snoozes

- GIVEN an unread `compras.faltantes` banner
- THEN the banner MUST show an **X** control
- WHEN the operator presses **X**
- THEN the client MUST `PATCH .../snooze`
- AND the banner MUST leave the stack for the snooze window
- AND after the snooze window, if still unresolved, the banner MAY reappear (existing behavior)

#### Scenario: Faltantes Ver navigates without dismiss

- GIVEN an unread `compras.faltantes` banner
- WHEN the operator presses **Ver**
- THEN the client MUST navigate to the pedido deep-link
- AND MUST NOT call `PATCH .../ok`
- AND MUST NOT call `PATCH .../snooze`

#### Scenario: Faltantes permanent clear stays on resolution

- GIVEN an unread `compras.faltantes` notification
- WHEN the responsable saves the required resolution texto and the pedido moves to faltantes-con-resolución
- THEN the faltantes alert MUST clear permanently via the existing resolve/retract path
- AND that path MUST NOT be replaced by Ver or X
