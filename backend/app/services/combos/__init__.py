"""App-owned combo bill of materials (combos-propios).

- `reconcile`: pure, source-agnostic diff of a desired snapshot against the stored rows.
- `store`: reads and writes `combo_componentes`.
- The source adapter that builds the snapshot (today from the ERP) comes in a following change.
"""
