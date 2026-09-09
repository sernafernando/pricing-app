# Proposal: Stable paging for Acciones masivas resolve

## Intent

Address owner review on PR #1245 (`CHANGES_REQUESTED`): client-side `resolveFilteredItemIds` must page with a stable `ORDER BY`, detect duplicate/omit via dedupe + mismatch, always enforce mismatch vs `totalProductos` when finite, and bound the page loop.

## Why

Without `orden_campos`/`orden_direcciones`, `productos_listing` pages with bare `OFFSET`/`LIMIT`. Postgres can duplicate/omit rows across pages; duplicates can cancel omissions so `ids.length === totalProductos` and the mismatch guard never fires — unsafe for a price-writing path.

## Scope

- In: `resolveFilteredItemIds.js` + covering Vitest; delta notes on stable order / mismatch / maxPages.
- Out: PR2 wiring/desync; backend listing schema; Calcular Web/PVP.

## Relationship

Amends / follows `fix-markup-masivo-filtro` (review remediation on open PR1).
