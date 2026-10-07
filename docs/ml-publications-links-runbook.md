# ML publications: product links (manual backup) runbook

Every publication unit `(item_id, variation_id)` is linked to one of our products automatically by SKU
(`links.enabled`). These endpoints are the operator's manual backup: fix a wrong link, link by hand, mark
"no product", or hand a unit back to the automatic rule. Backend only; the UI ships with the Publicaciones view.

`variation_id = 0` is the item-level unit of an item without variations; an item with variations has one unit per
variation. Manual always wins: once a unit is `manual` or `manual_none`, the SKU rule only refreshes its
suggestion and never moves the link.

## Permissions and flags

- Reads need `ml_ops.ver`. They work whether `links.enabled` is on or off.
- Writes need `ml_publicaciones.vincular` (ADMIN by default; anyone else through the per-user overrides screen).
- Writes are refused with 409 while `links.enabled` is off: turning linking off freezes the link table.
- With `events.enabled` on, every effective change also writes one `product_link_changed` event. The change-log
  row (`product_link`) and one `auditoria` row are written in the same transaction either way.
- The author of a write is always the authenticated user; a request body naming one is refused with 422.

## Reading

    GET /api/ml-publications/items/{item_id}/product-links
    GET /api/ml-publications/product-links
    GET /api/ml-publications/product-links/coverage

- The first returns the item's units with their stored link and the SKU suggestion as the rule says now
  (`suggestion.differs` is true when a manual decision disagrees with it; conflicts list every candidate with
  `codigo` and `descripcion`). 404 for an item the store does not hold.
- The second takes `class=unmatched|conflict|manual_differs|dangling`, `limit` (1 to 200) and the
  `cursor` returned as `next_cursor` by the previous page. Pages are keyset on `(item_id, variation_id)`.
- The third is the coverage report: counts by class and item status, plus up to `samples` (0 to 50) units per class.

## Writing

    PUT /api/ml-publications/items/{item_id}/product-links/{variation_id}
    PUT /api/ml-publications/items/{item_id}/product-links/{variation_id}/none
    POST /api/ml-publications/items/{item_id}/product-links/{variation_id}/revert-auto

- The first body is `{"producto_item_id": <id>, "note": "<optional>"}`. 422 when the product does not exist or the
  variation is not part of the item; 404 when the item is unknown.
- `none` takes `{"note": "<optional>"}` and records "explicitly no product" (different from `unmatched`).
- `revert-auto` returns the unit to the automatic rule, resolved immediately with the current SKU and catalog.
- Repeating the same decision changes nothing and writes no history. There is no DELETE: `revert-auto` is the way back.
- Every write answers `{"changed": <bool>, "unit": {...}}`; `changed` is false when only the note moved or nothing did.

## Suggested pass after enabling links

1. Set `links.enabled` (and `events.enabled` if events are wanted) and request a `relink` run.
2. Read the coverage report; open the `conflict`, `unmatched` and `dangling` lists.
3. Fix wrong or missing links with the writes above; check `manual_differs` after SKU changes.

## Rollback

Turn `links.enabled` off (writes stop with 409, rows are kept). The permission migration downgrades cleanly
(removes overrides, role grants and the permission); the router include in `app/main.py` can be reverted alone.
