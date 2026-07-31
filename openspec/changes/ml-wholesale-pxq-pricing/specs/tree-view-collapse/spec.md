# tree-view-collapse Specification

## Purpose

Globally synchronized expand/collapse across the publication tree (producto -> MLA -> promos ->
PxQ), replacing per-node local state that requires opening sections one by one.

## Requirements

### Requirement: Global synchronized toggle
One control MUST open or close every section across every MLA and product in the tree, including
nested promo and PxQ panels, in a single action.

#### Scenario: Global open
- GIVEN a tree with multiple products, MLAs, and nested promo panels in mixed open/closed states
- WHEN the user activates global-open
- THEN every section at every level becomes open

#### Scenario: Global close
- GIVEN a tree with sections open
- WHEN the user activates global-close
- THEN every section at every level becomes closed

### Requirement: Manual toggle survives global state
After a global toggle, a subsequent manual per-node toggle MUST take effect and MUST NOT be
overridden back by the prior global state.

#### Scenario: Manual override after global-open
- GIVEN the user just triggered global-open
- WHEN the user manually collapses one specific node
- THEN that node stays collapsed while other nodes remain open
