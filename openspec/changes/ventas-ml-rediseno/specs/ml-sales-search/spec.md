# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-sales-search

### Requirements
- R25 A search bar filters the listing server-side, through the shared filter builder (so search combines correctly with facets and toggles), matching at least: order id, pack id, MLA (item id), SKU, title, buyer nickname.
- R25a The title and SKU matches (R25) are text searches over the sale's own item title and `producto_item_id`-resolved `seller_sku` (i.e. the frozen item actually sold), not a live catalog lookup — extended per the user's 2026-09-22 binding decision to add product-oriented filters to this screen.
- R26 Search results respect all currently active filters and toggles (intersection, not replacement) — including the product-level facet filters of `ml-sales-product-filters`.
- R27 An empty/no-match search state is explicit (no orders shown, not an error).

### Scenarios
1. Given the user searches by an exact order id, when results return, then only that order (and its pack siblings if applicable) appears.
2. Given the user searches by a partial product title, when results return, then all matching orders across the currently active filters/toggles appear — orders excluded by an active toggle do NOT appear even if they match the search text.
3. Given a search term matches no orders, when results return, then the table shows an explicit empty state and the KPI strip reflects zero/empty aggregates for that combination — not a stale previous result.
4. Given the user searches by buyer nickname, when results return, then only orders belonging to that buyer nickname appear.
