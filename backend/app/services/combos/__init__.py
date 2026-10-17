"""App-owned combo bill of materials (combos-propios).

- `reconcile`: pure, source-agnostic diff of a desired snapshot against the stored rows.
- `store`: reads and writes `combo_componentes`.
- `fuente_erp`: the only ERP-aware piece, builds the snapshot from the current ERP.
"""
