# Delta for pedidos-compra

## MODIFIED Requirements

### Requirement: Pedido responsable

`pedidos_compra` MUST have `responsable_id`. On create it MUST default to `created_by`. Existing rows MUST backfill `responsable_id = created_by`. PATCH/editar editors MUST be admin or the pedido creator only. When marking faltantes, Depósito MAY set `responsable_id` on that mark path only. A newly chosen value MUST identify an active holder of `administracion.gestionar_ordenes_compra`. The current `responsable_id` MUST remain valid even if that user is outside the pool.

(Previously: editors MUST be admin or the pedido creator only; no faltantes-mark exception.)

#### Scenario: Default and backfill to creator

- GIVEN a new pedido created by user C, and a legacy row with null responsable
- WHEN create and backfill run
- THEN both MUST have `responsable_id = C` / `created_by`

#### Scenario: Non-editor cannot change responsable

- GIVEN pedido created by C, actor U is neither admin nor C
- WHEN U changes `responsable_id` via PATCH/editar
- THEN the system MUST reject the change

#### Scenario: Depósito may set responsable on faltantes mark

- GIVEN P with responsable R; actor D holds `deposito.recibir_mercaderia` and is neither admin nor creator
- WHEN D marks faltantes sending `responsable_id` = U who holds `administracion.gestionar_ordenes_compra`
- THEN P.responsable_id MUST become U

#### Scenario: Depósito PATCH still rejected

- GIVEN the same D and P
- WHEN D PATCHes `responsable_id`
- THEN the system MUST reject the change
