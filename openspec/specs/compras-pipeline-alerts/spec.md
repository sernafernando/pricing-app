# compras-pipeline-alerts Specification

## Purpose

In-app factura and faltantes alerts for the Compras pipeline. Reuse banner + campanita. No email or Slack.

## Requirements

### Requirement: In-app channel only

Factura and faltantes alerts MUST be in-app only (stackable `AlertBanner` until OK + campanita/`notificaciones`). The system MUST NOT send email or Slack for these events.

#### Scenario: Banner and campanita together

- GIVEN a factura or faltantes alert is created for user U
- WHEN U opens the app
- THEN U MUST see it in the stackable banner
- AND U MUST see it in campanita
- AND no email or Slack message MUST be sent

### Requirement: Alert copy uses Pricing P-number

Alert copy MUST include the Pricing pedido `P-…` number, proveedor name, and factura number. Copy MUST NOT use `pedidos_documento`.

#### Scenario: Factura alert copy

- GIVEN pedido `P-01-2026-00012`, proveedor `Acme`, factura `FA-99`
- WHEN a factura alert is created
- THEN copy MUST contain `P-01-2026-00012`, `Acme`, and `FA-99`
- AND copy MUST NOT contain `pedidos_documento`

### Requirement: Factura recipients and per-user OK

Factura-cargada recipients MUST be the UNION of marca titular, sub-PM, Admin, and Gerente. Each recipient MUST dismiss independently (per-user OK). The banner MUST stay stacked until that user OKs.

#### Scenario: Fan-out to union

- GIVEN a marca with titular T, sub-PM S, plus users Admin A and Gerente G
- WHEN factura is loaded with a nonempty number
- THEN T, S, A, and G MUST each receive the alert
- AND a user outside that union MUST NOT

#### Scenario: Per-user OK does not clear others

- GIVEN T and S both have the same factura alert
- WHEN T OKs
- THEN T’s banner/campanita item MUST clear
- AND S MUST still see the alert until S OKs

### Requirement: Faltantes alert to responsable

Marking faltantes MUST alert `pedido.responsable_id`. The mark MUST include nonempty free text. The alert MUST deep-link to pedido detalle with observaciones visible.

#### Scenario: Responsable notified with free text

- GIVEN pedido P with `responsable_id` = R
- WHEN depósito marks faltantes with free text `Faltan 2 cajas`
- THEN R MUST receive an in-app alert
- AND the alert MUST deep-link to P detalle showing observaciones
- AND the free text MUST be visible

#### Scenario: Faltantes without free text rejected

- GIVEN a pedido in a receivable state
- WHEN depósito marks faltantes with empty text
- THEN the system MUST reject the mark
- AND no faltantes alert MUST be created

### Requirement: Faltantes snooze one hour from mark

The responsable MAY snooze a faltantes alert. Snooze MUST hide it for 1 hour from the mark timestamp (not from snooze click). After the hour it MUST reappear until resolved or OK rules apply.

#### Scenario: Snooze until mark plus one hour

- GIVEN faltantes marked at 10:00
- WHEN the responsable snoozes at 10:20
- THEN the alert MUST stay hidden until 11:00
- AND at 11:00 it MUST reappear in banner and campanita

### Requirement: Faltantes resolution notifies depósito

When faltantes are resolved, the system MUST alert every user who holds `deposito.recibir_mercaderia`. Channel remains in-app only.

#### Scenario: All depósito receivers notified

- GIVEN users D1 and D2 hold `deposito.recibir_mercaderia`, and D3 does not
- WHEN faltantes on pedido P are resolved
- THEN D1 and D2 MUST receive an in-app alert for P
- AND D3 MUST NOT


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

### Requirement: Factura-cargada fire requires deploy cron

`compras.factura_cargada` notifications MUST be created only by the durable sweep (`disparar_alertas_factura_pendientes`), not by the ERP check itself. Production MUST schedule `python -m app.scripts.dispatch_factura_cargada_alerts` at least once per minute. Missing crontab MUST be treated as an ops defect: pending rows stay unfired. The 5-minute `alerta_pendiente_hasta` delay MUST NOT change. Empty `pedido_factura_documentos.numero` MUST remain a notify no-op.

#### Scenario: Check alone does not notify

- GIVEN a factura row checked `cargada` at T0 with nonempty `numero`
- WHEN no sweep has run
- THEN no `compras.factura_cargada` notification MUST exist
- AND `alerta_pendiente_hasta` MUST be T0 + 5 minutes

#### Scenario: Cron sweep fires after the delay

- GIVEN that pending row and holders of `administracion.ver_alertas_factura`
- WHEN the dispatch script runs at or after `alerta_pendiente_hasta`
- THEN each holder MUST receive one in-app alert
- AND copy MUST include the supplier invoice `numero`, not only the pedido P-number

#### Scenario: Empty invoice number stays a no-op

- GIVEN a checked row whose `numero` is empty or whitespace
- WHEN the sweep runs after the delay
- THEN no notification MUST be created

### Requirement: Ops docs state cron and ADMIN-alone is not enough

Deploy/runbook docs MUST name the factura-cargada cron command. Operator docs MUST state that the **ADMIN role alone does not grant** factura-cargada alerts; the user MUST hold `administracion.ver_alertas_factura`. Docs MUST NOT instruct agents to assign that permission in DB (Chicho owns assignment).

#### Scenario: Runbook names the dispatch command

- GIVEN `docs/RUNBOOKS.md` (or the Compras post-deploy checklist)
- WHEN an operator looks up factura-cargada alerts
- THEN the doc MUST include `python -m app.scripts.dispatch_factura_cargada_alerts`
- AND MUST state the job is required for alerts to fire

#### Scenario: Guía says ADMIN role is insufficient

- GIVEN `docs/modulos/compras-guia-usuario.md` (or in-app novedades)
- WHEN an operator reads who receives factura-cargada alerts
- THEN the text MUST say the ADMIN role is not enough
- AND MUST name `administracion.ver_alertas_factura`
