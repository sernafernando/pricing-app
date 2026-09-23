# Delta for vincular-oc

## ADDED Requirements

### Requirement: Linked OC remains when ERP lines are missing

A linked OC identity MUST remain on the pedido when the ERP header or lines are missing. The system MUST still expose that link (one block identity). Missing ERP data MUST NOT unlink the OC.

#### Scenario: ERP-missing OC stays linked

- GIVEN P1 linked to OC-A and ERP has zero lines for OC-A
- WHEN Depósito or link queries load P1
- THEN OC-A MUST still be linked
- AND the link MUST remain available to render

### Requirement: Desvincular unlinks all OCs

`DELETE .../desvincular-oc` MUST remove every OC link for that pedido (unlink-all) and MUST clear the header OC cache. Operator-facing docs MUST state this all-or-nothing asymmetry unless a later cheap granular delete ships. Granular per-OC unlink is out of scope unless apply finds it cheap.

#### Scenario: Desvincular clears every link

- GIVEN P1 linked to OC-A and OC-B
- WHEN desvincular-oc succeeds
- THEN P1 MUST have zero OC links
- AND header OC cache MUST be empty

#### Scenario: Asymmetry is documented

- GIVEN unlink remains all-or-nothing
- WHEN operator docs for this change are published
- THEN they MUST state that desvincular removes all linked OCs
