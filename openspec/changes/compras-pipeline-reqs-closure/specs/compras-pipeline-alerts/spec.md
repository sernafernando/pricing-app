# Delta for compras-pipeline-alerts

## ADDED Requirements

### Requirement: compras.faltantes dismiss rejected

OK and dismiss of `compras.faltantes` MUST be rejected (HTTP 409). That alert MUST clear only when faltantes are resolved and the item is retracted. Snooze MUST remain allowed. The factura-cargada timer, recipients, persist/Match-no-alert model, and two 5-minute windows MUST remain unchanged.

#### Scenario: Banner OK rejected

- GIVEN an open `compras.faltantes` alert for pedido P
- WHEN the user OKs or dismisses it
- THEN the system MUST respond HTTP 409
- AND the alert MUST remain visible

#### Scenario: Resolve retracts the alert

- GIVEN an open `compras.faltantes` for P
- WHEN a writer resolves faltantes with nonempty texto
- THEN `compras.faltantes` for P MUST be retracted
- AND the banner MUST clear for that item

#### Scenario: Snooze still allowed

- GIVEN an open `compras.faltantes` marked at 10:00
- WHEN the responsable snoozes at 10:20
- THEN the alert MUST stay hidden until 11:00
- AND it MUST NOT be discarded

## MODIFIED Requirements

### Requirement: Faltantes snooze one hour from mark

The responsable MAY snooze a faltantes alert. Snooze MUST hide it for 1 hour from the mark timestamp (not from snooze click). After the hour it MUST reappear until resolve/retract. OK/dismiss MUST NOT clear `compras.faltantes`.

(Previously: reappear “until resolved or OK rules apply” left banner OK as a valid clear.)

#### Scenario: Snooze until mark plus one hour

- GIVEN faltantes marked at 10:00
- WHEN the responsable snoozes at 10:20
- THEN the alert MUST stay hidden until 11:00
- AND at 11:00 it MUST reappear in banner and campanita

### Requirement: Faltantes resolution notifies depósito

Resolving faltantes MUST require nonempty `texto`, MUST stamp `faltantes_resuelto_en`, MUST retract `compras.faltantes` for that pedido, and MUST emit G31 `compras.faltantes_resuelto` to every user who holds `deposito.recibir_mercaderia`. G31 copy MUST include the PM `texto` and MUST deep-link to Depósito for that pedido. Channel remains in-app only. Factura-cargada timer/model MUST NOT change.

(Previously: G31 fan-out only; texto optional; no retract; no Depósito deep-link.)

#### Scenario: All depósito receivers notified

- GIVEN users D1 and D2 hold `deposito.recibir_mercaderia`, and D3 does not
- WHEN faltantes on pedido P are resolved
- THEN D1 and D2 MUST receive an in-app alert for P
- AND D3 MUST NOT

#### Scenario: G31 includes PM texto and Depósito deep-link

- GIVEN P is resolved with texto `Comprar 2 cajas y entregar en dock`
- WHEN G31 `compras.faltantes_resuelto` is created
- THEN copy MUST include that texto
- AND the alert MUST deep-link to Depósito **Faltantes con resolución** for P (`eje=faltantes_con_res`)

#### Scenario: Empty resolve texto rejected

- GIVEN P with `eje_procesal=faltantes_sin_res`
- WHEN resolve is called with empty or whitespace `texto`
- THEN the system MUST reject the request
- AND `faltantes_resuelto_en` MUST stay null
- AND `compras.faltantes` MUST remain
