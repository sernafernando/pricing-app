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
