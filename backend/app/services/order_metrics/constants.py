"""Shared constants for the stored-metrics producer (design D2, D7, D10).

`CURRENT_FORMULA_VERSION` is bumped whenever the Gauss formula changes in a
way that makes previously-persisted `ml_order_metrics.formula_version <
CURRENT_FORMULA_VERSION` rows stale -- `order_metrics.reconcile` (PR6)
re-enqueues every such row. Version 1 is reserved for the pre-existing
formula this change replaces (every `ml_orders_ops.total_gauss` persisted
before this deploy, under the pre-#1311/#1313 rules, with no
`ml_order_metrics` row at all): PR1 ships version 2 as the FIRST value ever
written to this new column, so PR6's reconcile "no metrics row" branch
covers full backfill of every legacy order in the same pass as the formula
bump (design "Pending requirement from ml-ventas-neto-iibb-varios").

History of the value:

- 2: first value ever written (the formula this change introduced).
- 3: ventas-ml-varios-base-envio. The "% de varios" base adds the shipping
  that comes in (paid by the buyer + the Flex bonificación) without IVA, and
  the Flex bonificación is the sender's discounts plus the `loyal` receiver
  ones (it used to sum every receiver discount). Bumping it IS the backfill:
  `order_metrics.reconcile` re-enqueues every row below it and
  `order_metrics.drain` recomputes them (`docs/RUNBOOKS.md`, "Recomputing every
  stored Total Gauss").
"""

from __future__ import annotations

CURRENT_FORMULA_VERSION = 3
