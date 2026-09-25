# Delta for compras-pipeline-alerts

## ADDED Requirements

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
