# ML publications: notification topics checklist

The publications store learns that an item changed from the bridge table `webhook_latest`
(one row per `(topic, resource)`, the latest delivery). The intake job (`ml_publications.intake`)
reads ONLY the topics mapped in the `intake.topics` setting, and only for the seller in `ML_USER_ID`.
Topic names below are the exact production names.

## Status on 2026-10-06

Every topic in this table was already subscribed in the Mercado Libre application and was arriving in
`webhook_latest` on 2026-10-06 (distinct resources in the last hour, read-only capture on server-lenovo).
Nothing has to be subscribed in the ML panel to ship the first PRs.

| Topic | Required | Resource pattern | Target | Resources / hour |
|---|---|---|---|---|
| `items` | required | `/items/MLA<n>` | item, full bundle | 353 |
| `items_prices` | optional | `/items/MLA<n>/prices` | item prices and sale price | 56 |
| `catalog_item_competition_status` | optional | `/items/MLA<n>/price_to_win` | item competition | 19 |
| `public_offers` | optional | `/seller-promotions/offers/OFFER-MLA<n>-<n>` | item promotions | 24 |
| `public_candidates` | optional | `/seller-promotions/candidates/CANDIDATE-MLA<n>-<n>` | item promotions | 144 |
| `stock-locations` | optional | not sampled yet | user product stock | 58 |
| `user-products-families` | optional | not sampled yet | user products family | 6 |

There is no `user_products` topic: user product changes arrive through `items`, `stock-locations`
and `user-products-families`.

The patterns of `stock-locations` and `user-products-families` are NOT mapped in code: the capture holds
no sample of either. Fix the regex from one real `webhook_latest` row (read-only) before mapping them;
until then an entry for them in `intake.topics` is skipped with a warning.

## Never read

`price_suggestion` (the largest topic, about 756 resources per hour), `catalog_suggestions`,
`fbm_stock_operations` and `flex-handshakes` are subscribed but have no store resource in this change.
Intake never reads them: it queries only the topics present in `intake.topics`, and the code accepts
only the five topics with a captured pattern.

## Default

`intake.topics` defaults to `items` only (`ML_PUB_INTAKE_TOPICS`). `intake.enabled` is off by default.
Intake with refresh off only enqueues: the entries wait in `ml_pub_refresh_queue` until
`refresh.enabled` is turned on.

## Before adding a topic to `intake.topics`

1. Enable the matching fetcher first (its resource must be in `bundle_resources`, otherwise the queue
   entries are dropped uncharged at refresh time).
2. Confirm the topic still arrives, with a read-only count on the bridge database:

   ```sql
   SELECT count(*) FROM webhook_latest WHERE topic = 'items_prices' AND received_at > now() - interval '1 hour';
   ```

   A count of zero means the subscription was dropped in the ML application panel: fix it there first.
3. Set the value, for example (`PUT /ml-publications/settings/intake.topics` once the admin endpoints
   exist, or the settings CLI):

   ```json
   {"items": {"kind": "item", "resources": ["bundle"]},
    "items_prices": {"kind": "item", "resources": ["prices", "sale_price"]}}
   ```

4. Watch `ml_pub_intake_cursors` (one row per topic: cursor, rows read, enqueued, skipped, unparsed).

## Fallback coverage

Until a topic is mapped, its sub-resource is still covered: the `items` notification triggers the
full-bundle refresh, and the periodic rescans re-request every sub-resource enabled in
`bundle_resources`. Mapping a topic only makes that sub-resource fresher (seconds instead of the
rescan period); it never adds coverage that does not exist.
