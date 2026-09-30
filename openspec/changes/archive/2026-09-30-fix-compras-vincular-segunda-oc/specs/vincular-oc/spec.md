# Delta for vincular-oc

## ADDED Requirements

### Requirement: Detail Vincular OC stays available for another link

The pedido detail section **Orden de compra ERP** MUST show **Vincular OC** when the user has `administracion.gestionar_ordenes_compra` AND the pedido `tipo` is not `servicio`. A set header `oc_poh_id` MUST NOT hide the button. The action MUST open the existing Vincular OC modal and MUST call existing `POST /administracion/compras/pedidos/{id}/vincular-oc`. The system MUST NOT introduce a new permission. Candidate rules MUST stay unchanged (same supplier, pending lines, no duplicate triple). **Desvincular OC** MUST remain all-or-nothing.

#### Scenario: Mercadería with one OC still shows Vincular OC

- GIVEN a mercadería pedido with `oc_poh_id` set and the user has `administracion.gestionar_ordenes_compra`
- WHEN the operator opens pedido detail
- THEN **Vincular OC** MUST be visible
- AND **Desvincular OC** MUST remain visible

#### Scenario: Mercadería with no OC still shows Vincular OC

- GIVEN a mercadería pedido with no linked OC and the user has `administracion.gestionar_ordenes_compra`
- WHEN the operator opens pedido detail
- THEN **Vincular OC** MUST be visible

#### Scenario: Servicio hides Vincular OC

- GIVEN a pedido with `tipo=servicio` and the user has `administracion.gestionar_ordenes_compra`
- WHEN the operator opens pedido detail
- THEN **Vincular OC** MUST NOT be visible

#### Scenario: Missing permiso hides Vincular OC

- GIVEN a mercadería pedido (linked or not) and the user lacks `administracion.gestionar_ordenes_compra`
- WHEN the operator opens pedido detail
- THEN **Vincular OC** MUST NOT be visible

### Requirement: Pedido detail lists every linked OC

Pedido detail MUST list every linked OC identity. The list MUST use `ocs[]` when present and MUST fall back to the header triple (`oc_comp_id`, `oc_bra_id`, `oc_poh_id`) when `ocs` is empty. After a successful additional link, the operator MUST see the newly linked OC in that list without relying on only the first header `oc_poh_id`.

#### Scenario: Two linked OCs both appear in detail

- GIVEN a pedido linked to OC `#100` and OC `#200` (`ocs[]` has both triples; header still `#100`)
- WHEN the operator opens pedido detail
- THEN the Orden de compra ERP section MUST show both `#100` and `#200`
- AND it MUST NOT show only `#100`

#### Scenario: Single linked OC still appears

- GIVEN a pedido with one linked OC `#100` (header and/or `ocs[]`)
- WHEN the operator opens pedido detail
- THEN the section MUST show `#100`

#### Scenario: Second link is visible immediately

- GIVEN the operator just linked a second OC via the existing Vincular OC modal
- WHEN the modal reports success
- THEN detail MUST list the previous OC and the newly linked OC
