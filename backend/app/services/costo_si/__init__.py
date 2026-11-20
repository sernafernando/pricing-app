"""Costo SI (cost by sell in): the moving weighted average cost of every product, in USD (sell-in-costo-si T2).

Spec: handoffs/sell-in-costo-si-feature.md. `engine` is the pure arithmetic, `fuentes` reads its inputs (GBP mirror,
Compras, sell ins, ML Full), `full_ml` keeps ML's Full stock operations, `recompute` stores the result with a backup,
`queue` is the recompute-from-date queue that `sell.drain` drains.
"""
