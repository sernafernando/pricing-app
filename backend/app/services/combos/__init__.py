"""App-owned combo bill of materials (combos-propios).

- `reconcile`: pure, source-agnostic diff of a desired snapshot against the stored rows.
- `store`: reads and writes `combo_componentes` for the reconcile (takes its lock).
- `fuente_erp`: builds the snapshot from the current ERP.
- `componentes`: the lock-free read accessor every reader uses.
"""
