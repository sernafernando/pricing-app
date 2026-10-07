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

## Enabling the description, prices and sale_price fetchers

The refresh handler ships these three fetchers dark: they run only for resources listed in the
`bundle_resources` setting (default `["core"]`).

1. Enable one group at a time, watching the per-endpoint 429 counter in `worker_job_state.detail`:
   `bundle_resources = ["core", "prices", "sale_price"]` first, `description` afterwards.
2. A `bundle` request fetches every enabled resource whose minimum age (`min_age_seconds`) has
   passed since its last check: `description` waits 6 h, `prices` and `sale_price` have no minimum.
   A request that names the resource (`prices`, `sale_price` from a price topic, or a manual
   enqueue) bypasses the minimum age. `skipped_min_age` counts what the age skipped.
3. `sale_price.reference_date` is the response time, so it is excluded from the change log (a fetch
   that only moves it refreshes raw and writes no row); every real change is logged and, with
   `events.enabled`, produces `price_changed` events of kind `standard`, `promotion` or `sale`.
4. A sub-resource that answers non-2xx is stored with its status and error body and retried alone;
   an item whose core answers 404 gets no sub-resource calls.

Rollback: remove the names from `bundle_resources`; nothing already stored is deleted.

## Enabling the promotions fetcher

The refresh handler ships the promotions fetcher dark. It calls ML
(`GET /seller-promotions/items/{id}?app_version=v2`, the same ML application the bridge uses) only when
BOTH gates are open:

1. `promotions.enabled` is on (it is off by default; `ML_PUB_KILL_SWITCH` overrides it), and
2. `promotions` is listed in `bundle_resources` (default `["core"]`).

With only one of them, an entry that asks for promotions is dropped uncharged and counted in
`skipped_disabled`; no call is made. The store keeps the answer in `ml_item_seller_promotions` (raw list,
one change-log row per real change keyed by promotion `id`, else `type`) and, with `events.enabled`,
derives `promotion_offered`, `promotion_activated`, `promotion_finished` (payload `reason`: `ended`,
`withdrawn` or `absent`) and `promotion_price_changed`. The bridge promotion mirror
(`ml_item_promotions`) is never read or written.

A `bundle` refresh fetches promotions at most every 300 s per item (`min_age_seconds`, default 300 s);
an entry that names `promotions` bypasses that age. To make promotions react to ML notifications, map
the two topics (promotions-only entries are claimable 60 s after the notification, so a burst for one
item becomes one fetch). Not part of the default map:

```json
{"items": {"kind": "item", "resources": ["bundle"]},
 "public_offers": {"kind": "item", "resources": ["promotions"]},
 "public_candidates": {"kind": "item", "resources": ["promotions"]}}
```

Cost (capture of 2026-10-06, distinct resources in the last hour): `public_candidates` 144 and
`public_offers` 24, so at most about 170 items per hour (about 4k per day). The queue key collapses
repeats of one item, the 60 s debounce groups a burst, and the 300 s minimum age bounds the bundle
path: the promotions fetch stays at about 0.05 req/s of the 2 req/s global budget (lane 1 shares it with
everything else). Keep the defaults; they are justified by those numbers.

Order to turn it on, one step at a time, watching `promotions` in the per-endpoint counters of
`worker_job_state.detail`:

1. `bundle_resources = ["core", "promotions"]` and `promotions.enabled = true`, then enqueue one item.
2. Add `public_offers` and `public_candidates` to `intake.topics`.

Rollback: set `promotions.enabled = false` (or remove `promotions` from `bundle_resources`) and remove
the two topics from `intake.topics`; nothing already stored is deleted.
