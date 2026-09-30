# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Pedidos list compact poh chips for multiple OCs

When a Pedidos list row has `ocs.length > 1`, the row MUST show a compact `#{oc_poh_id}` label for each linked OC. A row with exactly one OC MUST keep the OC chip and MUST NOT add those extra poh labels. This change MUST NOT regress that list behavior.

#### Scenario: Two OCs show compact poh labels

- GIVEN a Pedidos list row with `ocs` of `#100` and `#200`
- WHEN the list renders
- THEN compact labels `#100` and `#200` MUST be visible
- AND the OC chip MUST remain

#### Scenario: Single OC has no extra poh labels

- GIVEN a Pedidos list row with exactly one linked OC
- WHEN the list renders
- THEN the OC chip MUST be visible
- AND extra `#{oc_poh_id}` poh labels MUST NOT appear
