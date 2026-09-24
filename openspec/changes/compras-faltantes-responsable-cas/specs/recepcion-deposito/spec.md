# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: Responsable picker on mark faltantes

When Depósito marks faltantes (CON-OC ingresos or SIN-OC confirmar), the UI MUST let the operator pick `responsable_id`. Default MUST be the pedido’s current responsable. Options MUST be current ∪ holders of `administracion.gestionar_ordenes_compra`. Omit or same-as-current MUST keep the current value. Control-complete MUST ignore any sent `responsable_id`.

#### Scenario: Default current on mark

- GIVEN P.responsable_id = R
- WHEN Depósito opens mark-faltantes
- THEN the picker MUST default to R
- AND R MUST stay listed even if R lacks `administracion.gestionar_ordenes_compra`

#### Scenario: Chosen pool member persisted

- GIVEN holder U of `administracion.gestionar_ordenes_compra`
- WHEN Depósito marks faltantes with `responsable_id` = U
- THEN P.responsable_id MUST be U

#### Scenario: Invalid chosen rejected

- GIVEN user X is inactive or lacks `administracion.gestionar_ordenes_compra` and X is not current
- WHEN Depósito marks faltantes with `responsable_id` = X
- THEN the system MUST reject (HTTP 422)
- AND P.responsable_id MUST stay unchanged

#### Scenario: Control complete does not reassign

- GIVEN P.responsable_id = R
- WHEN Depósito marks control complete sending another `responsable_id`
- THEN P.responsable_id MUST stay R

### Requirement: Responsable pool for faltantes

Depósito MUST be able to load the picker pool: active users who hold `administracion.gestionar_ordenes_compra`. Callers who lack `deposito.recibir_mercaderia` MUST NOT receive that pool.

#### Scenario: Pool is gestionar_ordenes_compra holders

- GIVEN U holds `administracion.gestionar_ordenes_compra` and V does not
- WHEN Depósito loads the pool
- THEN U MUST appear
- AND V MUST NOT (unless V is current on that pedido)

#### Scenario: Non-deposito cannot load pool

- GIVEN actor A lacks `deposito.recibir_mercaderia`
- WHEN A requests the pool
- THEN the system MUST reject (HTTP 403)
