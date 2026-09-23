# Delta for compras-pipeline-alerts

## MODIFIED Requirements

### Requirement: Faltantes alert to responsable

Marking faltantes MUST alert `pedido.responsable_id` after any mark-path assign. The mark MUST include nonempty free text. The alert MUST deep-link to pedido detalle with observaciones visible.

(Previously: alerted whatever `responsable_id` already was; no assign-then-alert.)

#### Scenario: Responsable notified with free text

- GIVEN pedido P with `responsable_id` = R
- WHEN depósito marks faltantes with free text `Faltan 2 cajas` and omits a new responsable
- THEN R MUST receive an in-app alert
- AND the alert MUST deep-link to P detalle showing observaciones
- AND the free text MUST be visible

#### Scenario: Faltantes without free text rejected

- GIVEN a pedido in a receivable state
- WHEN depósito marks faltantes with empty text
- THEN the system MUST reject the mark
- AND no faltantes alert MUST be created

#### Scenario: Chosen responsable receives the alert

- GIVEN P.responsable_id = R and holder U of `administracion.gestionar_ordenes_compra`
- WHEN depósito marks faltantes with texto and `responsable_id` = U
- THEN U MUST receive the `compras.faltantes` alert
- AND R MUST NOT receive that new alert
