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

#### Scenario: Manual control ends the global cascade
- GIVEN the user triggered global-open, then manually collapsed a node
- WHEN the user manually expands that node again
- THEN its subtree renders with its own sections closed, not force-opened by the earlier global-open
- AND every node the user opens by hand from then on expands one level only

### Requirement: A manual toggle returns the view to manual mode
A manual per-node toggle MUST return the global collapse mode to `manual`, WITHOUT advancing the
global activation counter.

A node's children only mount once that node is open, so a global-open reaches an unmounted subtree
through the mount cascade rather than in a single pass. That cascade MUST NOT outlive the global
action: without this requirement, every node the user opens by hand after one global-open would
re-expand its whole subtree for the rest of the session, and a normal single-level expand would
become impossible.

Leaving the activation counter untouched is what keeps already-mounted nodes exactly as the user
left them — only future mounts are affected.

#### Scenario: Manual toggle resets the mode
- GIVEN the global mode is `all-open` after a global-open
- WHEN the user manually toggles any node or section
- THEN the global mode becomes `manual`
- AND the global activation counter is unchanged
