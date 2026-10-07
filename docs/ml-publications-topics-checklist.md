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
repeats of one item, the 60 s debounce (env `ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS`) groups a burst, and the 300 s minimum age bounds the bundle
path: the promotions fetch stays at about 0.05 req/s of the 2 req/s global budget (lane 1 shares it with
everything else). Keep the defaults; they are justified by those numbers.

Order to turn it on, one step at a time, watching `promotions` in the per-endpoint counters of
`worker_job_state.detail`:

1. `bundle_resources = ["core", "promotions"]` and `promotions.enabled = true`, then enqueue one item.
2. Add `public_offers` and `public_candidates` to `intake.topics`.

Rollback: set `promotions.enabled = false` (or remove `promotions` from `bundle_resources`) and remove
the two topics from `intake.topics`; nothing already stored is deleted.

## Enabling the user product, stock and family fetchers

The refresh handler ships these three fetchers dark: they run only for resources listed in
`bundle_resources` (default `["core"]`). Add `user_product`, `stock` and `family` one at a time, watching the
per-endpoint 429 counters in `worker_job_state.detail`.

- `user_product` (`GET /user-products/{id}`), `stock` (`GET /user-products/{id}/stock`, `locations[]` with
  `type` and `quantity`) and `family` (`GET /sites/MLA/user-products-families/{family_id}`).
- An item `bundle` reaches them through the stored item row (`user_product_id`, `family_id`). An item with
  none skips them (`skipped_not_applicable`, not a failure); two items of one user product in a batch fetch
  it once (`skipped_shared`).
- Minimum ages on a `bundle` request (`min_age_seconds`): `user_product` and `stock` 15 min, `family` 24 h.
  A request that names the resource bypasses them.
- Queue entries of kind `user_product` (ids `MLAU...`) and `family` (the numeric family id) carry no item and
  fetch only their own resources (`bundle` means `user_product` + `stock` for a user product). They can be
  enqueued through `ml_pub_refresh_queue`; nothing produces them yet (the enqueue CLI takes items only and no
  topic is mapped, see below), so today the item `bundle` is the way these resources are filled.
- `stock` has its own pacing sub-budget on top of the global one: `ML_PUB_STOCK_RATE_PER_MIN` (default 60,
  at most the 100 requests per minute ML documents). A backfill of every item pays it: about 24.7k items,
  fewer distinct user products, so expect the stock sub-budget, not the global 2 req/s, to set the pace.
- A stock answer of 403 is stored with its status and error body, surfaced in the queue entry's
  `last_error` (`stock: HTTP 403`) and retried alone; the user product and family still apply.
- Stock zero-crossing events (`stock_depleted`, `stock_replenished`) stay on the item core
  (`available_quantity`); these three resources raise no events.

Topics: `stock-locations` (resource `/user-products/$ID/stock` in the ML application) and
`user-products-families` are NOT mapped in code: `webhook_latest` held no row of either when the capture was
taken, and a resource pattern is never invented. Until one is fixed, an entry for them in `intake.topics`
is skipped with a warning. To fix a pattern, take real rows read-only on the bridge, commit them as fixtures
(`webhook_latest_samples.json`), then write the regex and its test:

```sql
SELECT topic, resource FROM webhook_latest WHERE topic IN ('stock-locations','user-products-families') LIMIT 3;
```

Until then the stock and family stay as fresh as the `items` notification and the rescans make them (every
sale fires an `items` notification, and the item bundle re-checks them past their minimum age).

Rollback: remove the names from `bundle_resources`; nothing already stored is deleted.

## Enabling competition, moderation, performance and visits

The refresh handler ships four more fetchers dark. Each makes no ML call until its name is listed in
`bundle_resources` (default `["core"]`); a name that is not listed is dropped uncharged and counted in
`skipped_disabled`. Rows go to `ml_item_competition`, `ml_item_moderations`, `ml_item_performance` and
`ml_item_visits`; the answers are kept raw with one change-log row per real change.

| Resource | Endpoint | Asked when | Bundle min age (`ML_PUB_MIN_AGE_SECONDS`) |
|---|---|---|---|
| `competition` | `GET /items/{id}/price_to_win?version=v2` | the stored item has `catalog_listing = true`, on the bundle and when named | 900 s |
| `moderation` | `GET /moderations/last_moderation/{id}-ITM` | on the bundle: status `under_review`, or a moderation sub_status/tag (below); when named: always | 3600 s |
| `performance` | `GET /item/{id}/performance` | only when an entry names it (the sweep does); never on the bundle | none |
| `visits` | `GET /items/{id}/visits/time_window?last=30&unit=day` | only when an entry names it; never on the bundle | none |

Notes, all from the 2026-10-06 captures:

- An item that is not a catalog listing gets no `price_to_win` request and no row, even when `competition` is named
  (`skipped_not_applicable` counts it). The core of the same run is stored first, so the decision reads fresh data.
  An entry that names `competition` for an item that is not stored yet (its notification can come first) cannot be
  decided: its core is queued first (counter `requeued_for_core`) and the entry is refetched in the same run.
- A competition row is never deleted. If an item later stops being a catalog listing, its row keeps the last status
  and no event is raised (no `catalog_competition_lost`); read `ml_item_competition` together with
  `ml_items.catalog_listing`.
- A moderation `404 {"Status": 404}` means "no moderation": it is stored as `has_moderation = false`, not as gone, not
  as a failure, and raises no `item_gone`. Any other 404 body is a missing resource and marks the row gone.
- Performance of a catalog product item answers `400 "Entity not calculated: Product items are not supported"`: stored
  as `applicable = false`, the queue entry completes without a charged attempt. Any other 400 is a failure.
- Performance and visits are sweep-only (no ML notification, high cost per sale-triggered event). Listing them in
  `bundle_resources` only allows a NAMED request; a `bundle` entry skips them. The sweep (see "Missed feeds and
  sweeps" below) is what names them.
- Visits `results` are diffed by `date`: a daily refetch logs the day that entered or left the 30-day window, never the
  whole window.
- With `events.enabled`: `catalog_competition_won` / `catalog_competition_lost` (the status becomes or stops being
  `winning`) and `moderation_applied` / `moderation_resolved` (a moderation record appears, or the answer goes back to
  the no-moderation 404).

Known gaps, stated rather than guessed:

- No moderation record was captured (no item was under review on 2026-10-06). A 200 is stored unchanged and typed only
  as `has_moderation = true`; what a record says (restrictive, resolved) is not interpreted until a real one is
  captured. No losing competition sample was captured either: `lost` is tested on a real winning body with one field
  changed.
- The moderation sub_status/tag set that makes the bundle ask (`forbidden`, `waiting_for_patch`, tag
  `moderation_penalty`) comes from the ML documentation, not from a capture. A value missing from it only means the
  bundle does not ask; a named `moderation` entry always does.

Intake can keep competition fresh from its notification topic (19 resources per hour on 2026-10-06, so the default
900 s age is never the limit). Not part of the default map:

```json
{"items": {"kind": "item", "resources": ["bundle"]},
 "catalog_item_competition_status": {"kind": "item", "resources": ["competition"]}}
```

Order to turn it on, one resource at a time, watching its counters in `worker_job_state.detail`:

1. `bundle_resources = ["core", "competition"]`, then enqueue one catalog item and read its `ml_item_competition` row.
2. Add `moderation`, then `catalog_item_competition_status` to `intake.topics`.
3. `performance` and `visits` through the sweep (see "Missed feeds and sweeps" below).

Rollback: remove the names from `bundle_resources` (and the topic from `intake.topics`); nothing already stored is
deleted, and the migration `20261007_ml_publications_quality` downgrades by dropping its four tables.

## Missed feeds and sweeps

Two more jobs of the `pricing-worker-ml` worker, each behind its own flag (default off, independent of each other
and of every other flag). Neither adds a cron, a timer or a LISTEN/NOTIFY: the schedule is the generic worker's
`interval`.

| Job | Handler | Schedule | Flag | What it does |
|---|---|---|---|---|
| Missed feeds | `ml_publications.missed_feeds` | every 2 hours | `missed_feeds.enabled` | pages ML `/missed_feeds` (app and topic scoped, site MLA) for each topic of `intake.topics` and enqueues the resources in the reconcile lane (2), through the same topic parser as intake |
| Sweep | `ml_publications.sweep` | every 10 minutes | `sweep.enabled` | enqueues the oldest `ceil(eligible / 144)` items for performance and for visits in the sweep lane (4), naming the resource; makes no ML call itself |

### Missed feeds

* ML keeps undelivered notifications for 2 days. A run pages with `limit` 20 and `offset` until ML answers
  `{messages: null}` (the end of the list; a short page does not end it). Only `resource`, `topic`, `user_id` and
  `received` of a message are read: the delivery attempt (`request`, `response`) is never stored.
* A resource already fetched after the missed delivery needs no refresh and is not enqueued; another seller's
  message is dropped; each resource is enqueued once per run however many pages repeat it.
* Only a completed run is a success: a list that every run leaves partial and never finishes is, by definition, a gap.
* If the last successful run is older than 48 h, the run records a coverage gap in its `ml_pub_job_runs` row
  (`counts.coverage_gap`) and requests a scan rescan (`worker_job_state.state = 'requested'` for
  `ml_publications.scan`, honored once `scan.enabled` is on), once per gap.
* A run that does not finish (worker deadline, flag turned off, 429) continues from its page on the next pass
  (`worker_job_state.detail.resume`; a position older than 3 hours is dropped and the list is read again from the first
  page, because ML trims it from the front). A failed run waits 1, 2, 4, ... minutes (at most 1 hour) before the next try
  (`detail.failures`, `detail.retry_at`); a missing `ML_USER_ID` / `ML_CLIENT_ID` or a rejected token ends the run as
  `blocked` until the setup is fixed.
* Known gap: the capture does not say in which order ML returns the messages. If it trims the list at the end the
  run pages from, a run that resumes can skip messages without noticing; the 3 hour limit on a saved position, the
  next 2-hourly run and the rescan requested after a gap of more than 48 h bound that risk.
* Known gaps: the capture's calls for `stock-location` and `user_products` used wrong topic names (there is no such
  topic), so only their shape (`{messages: null}`) is evidence. The 20 messages per page is a conservative choice:
  the capture used `limit=5` and ML's ceiling is not in it.

### Sweeps

* `performance` and `visits` have no notification topic. Eligible: status in `sweep.statuses` (default every
  non-closed status: `active`, `paused`, `under_review`, `inactive`, `pending`; `closed` is never swept and is
  rejected by the setting), not gone. A performance state stored as `not_applicable` (a catalog product item) is
  rechecked only after `ML_PUB_NOT_APPLICABLE_RECHECK_DAYS` (30 days). Visits are one item per call.
* With `refresh.enabled` off the entries only wait in the queue (nothing fetches them), and while live entries wait
  (intake keeps enqueuing) the tick records `yielded`: expected, not a fault (each tick's run record
  carries `yielded_in_a_row`; a long streak, logged as a warning at 36 ticks, means live work is starving the sweep).
* Only the resources listed in `bundle_resources` are swept: add `performance` and/or `visits` first, or the tick
  records `no_resources` and does nothing.
* The tick enqueues nothing while manual or notification-lane work is ready to be claimed (it yields), skips
  items that already have a queue entry (an item whose entry is parked, that is, failed past its attempts, is not
  eligible at all until it is enqueued by hand in the manual lane), and stops adding work while 3 ticks' worth of sweep entries wait unfetched
  (a stopped `refresh.enabled` cannot make the queue grow).
* Sizing (2026-10-06): about 24.6k eligible items (16.2k of them paused) x 2 resources = about 49k calls a day =
  0.57 req/s, close to 30% of the 2 req/s budget. With `sweep.statuses = ["active"]` (about 7.8k items) it is about
  15.6k calls a day = 0.18 req/s. Each tick's run record carries `calls_per_day` and `requests_per_second`.

The sweep handler reports success even when a tick fails (the next tick, ten minutes later, retries it), so
`worker_job_state.last_success_at` is not a health signal for it: watch `outcome` and `last_error` in `ml_pub_job_runs`
where `job = 'sweep'`.

### Turning it on

Order, watching the 429 counter in `worker_job_state.detail.counters`:

1. Missed feeds (run it once by hand to see it work):
   `python -m app.scripts.ml_publications_settings set missed_feeds.enabled true` then
   `python -m app.scripts.ml_publications_request ml_publications.missed_feeds`.
   Check: `SELECT outcome, counts, last_error FROM ml_pub_job_runs WHERE job = 'missed_feeds' ORDER BY id DESC LIMIT 3;`
   (outcome `success`, no `coverage_gap` after the first run).
2. Sweep, narrowed first:
   `python -m app.scripts.ml_publications_settings set sweep.statuses '["active"]'`
   `python -m app.scripts.ml_publications_settings set bundle_resources '["core","performance","visits"]'`
   `python -m app.scripts.ml_publications_settings set sweep.enabled true`
   Check: `SELECT outcome, counts FROM ml_pub_job_runs WHERE job = 'sweep' ORDER BY id DESC LIMIT 3;` (`eligible`,
   `batch`, `selected` per resource), performance/visits rows appearing in `ml_item_performance` / `ml_item_visits`,
   and `not_applicable` performance (`applicable = false`) not counted as failures.
3. Widen to every non-closed status when the first day stays within budget:
   `python -m app.scripts.ml_publications_settings set sweep.statuses '["active","paused","under_review","inactive","pending"]'`

Rollback: `python -m app.scripts.ml_publications_settings set missed_feeds.enabled false` and
`python -m app.scripts.ml_publications_settings set sweep.enabled false` (each at its own next tick; nothing stored is
deleted, queued entries are still served by the refresh handler). To stop only the fetching of performance and visits,
remove them from `bundle_resources`.

## Verification jobs

One more job of the `pricing-worker-ml` worker, `ml_publications.verify`, with two sub-jobs. Each is behind its own
flag (default off, independent of each other and of every other flag). Neither adds a cron, a timer or a
LISTEN/NOTIFY: the schedule is the generic worker's `run_at_local`.

| Sub-job | Flag | What it does |
|---|---|---|
| Divergence spot-check | `divergence.enabled` | samples stored items (`ML_PUB_DIVERGENCE_SAMPLE_SIZE`, default 50, taken in turn from every status), re-fetches them from `/items/bulk` in the sweep lane (4) through the shared pacer, compares the typed columns with the stored row and records the match rate and the (item, column) pairs that differ in `ml_pub_job_runs` (`job = 'divergence'`) |
| Freshness snapshot | `verify.enabled` | stores the freshness and completeness numbers of the status report (`job = 'freshness'`); no ML call |

Schedule: daily at 05:00 local time. A check that cannot finish (deadline, 429, flag turned off, or work of a higher
lane waiting) is a finished run with `complete: false`, not a failure: the worker runs it again 2 minutes later
and no snapshot is taken until it finishes. A check that fails is recorded
(`outcome = 'failed'`, `last_error`) and ends the day's slot; an operator request or tomorrow retries it. With both
flags off the handler returns without consuming its slot, so enabling it later the same day runs it at the next pass.

Reading a result:

- The rate is per item: an item agrees when none of its typed columns differs, so 3 of 100 items with another `status`
  is 97%. The target is 99%; a lower rate is `outcome = 'below_target'` and `below_target: true`.
- A difference is **not** divergence when the Store moved since the sample was taken (the item was fetched again, or a
  refresh is queued for it). Those are listed in `changed_after_sampling` and left out of the rate.
- An item ML no longer answers is `unverified` (not compared, not counted as a difference).
- `GET /status` reports the latest run under `verification.divergence` and `verification.snapshot`.

### Turning it on

1. Divergence on a sample of 50, run once by hand:
   `python -m app.scripts.ml_publications_settings set divergence.enabled true`
   (turning a flag on marks the handler `requested`, so it runs on the next worker pass; or
   `python -m app.scripts.ml_publications_request ml_publications.verify`).
   Check: `SELECT outcome, counts -> 'rate' AS rate, counts -> 'sampled' AS sampled, counts -> 'divergences' AS pairs, last_error FROM ml_pub_job_runs WHERE job = 'divergence' ORDER BY id DESC LIMIT 3;`
   Expect `outcome = 'success'`, `rate` at least 99 and about 3 calls (50 items, 20 per call, `lane` 4). A `below_target`
   run lists the pairs: look at the columns that repeat before enabling more sub-resources.
2. The snapshot:
   `python -m app.scripts.ml_publications_settings set verify.enabled true`
   Check: `SELECT outcome, counts -> 'items' FROM ml_pub_job_runs WHERE job = 'freshness' ORDER BY id DESC LIMIT 1;`

Rollback: `python -m app.scripts.ml_publications_settings set divergence.enabled false` and
`python -m app.scripts.ml_publications_settings set verify.enabled false` (a check in progress stops at its next
batch; nothing stored is changed, the jobs only read the Store and ML).

## Admin endpoints

The endpoints replace the CLIs for an operator without a shell. They live under `/api/ml-publications` and need a
bearer token. Reading needs `ml_ops.ver`; every action needs `ml_ops.gestionar`. Merging them turns nothing on: a
flag only changes when somebody `PUT`s it.

| Endpoint | Permission | What it does |
|----------|------------|--------------|
| `GET /status` | `ml_ops.ver` | Read-only report, no ML call, `statement_timeout` 5 s. |
| `GET /settings` | `ml_ops.ver` | Every setting with its effective value and source (`db`, `env`, `kill_switch`, `unreadable`). |
| `PUT /settings/{key}` | `ml_ops.gestionar` | Writes one allow-listed setting, recorded as `updated_by = user:<username>`. Turning a flag **on** marks its handler `requested`. |
| `POST /enqueue` | `ml_ops.gestionar` | Up to 100 items at lane 0 (`item_ids`, optional `resources`, default `["bundle"]`). |
| `POST /jobs/{job}/request` | `ml_ops.gestionar` | Runs a handler on the worker's next pass. `job` is `refresh`, `intake`, `relink`, `scan`, `missed_feeds`, `sweep`, `verify` or `divergence` (the last two run the same handler). `scan` accepts `{"mode": "full"}` or `{"mode": "rescan"}`. |

Examples (`$API` is the base URL, `$TOKEN` a bearer token):

```
curl -s -H "Authorization: Bearer $TOKEN" "$API/api/ml-publications/status"
curl -s -H "Authorization: Bearer $TOKEN" "$API/api/ml-publications/settings"
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"value": true}' "$API/api/ml-publications/settings/refresh.enabled"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"item_ids": ["MLA935110613", "MLA934406852"]}' "$API/api/ml-publications/enqueue"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"mode": "full"}' "$API/api/ml-publications/jobs/scan/request"
```

### Reading the status

- `jobs`: per handler `enabled`, `disabled` (the flag is off: a state, **not** a failure), `failing` (the last run is
  newer than the last success while enabled), `requested` and `last_error`. The runtime does not persist the
  `disabled` run outcome, so `disabled` comes from the effective flag (and from `detail.disabled` when present).
- `queue.lanes`: `waiting`, `claimed`, `parked` and `oldest_waiting_age_seconds` per lane; `queue.parked` lists up
  to 20 parked entries with their last error (`parked_total` is the real count).
- `intake.stalled`: the cursor has not advanced for more than `ML_PUB_INTAKE_STALL_SECONDS` (default 600) while
  `intake.enabled` is on. An old cursor with the flag off is not an alarm.
- `backfill`: progress per scan status (`enumerated`, `enqueued`, `restarts`, `complete`).
- `missed_feeds`: last completed run and its age, the last run, and `coverage_gap` (`resolved: true` once a later run
  completed).
- `sweep.last_run`: read **`outcome`** and `yielded_in_a_row` here; the sweep reports success to the runtime even
  when a tick fails, so its `last_success_at` says nothing.
- `verification`: `divergence` (the latest spot-check: `rate`, `below_target`, `sampled`, the diverging pairs and how
  many items changed after sampling) and `snapshot` (the latest freshness snapshot). Both are null until the jobs ran.
- `freshness`: p50/p95/max age over `last_checked_at`, per state table. `lag_p95_seconds_24h`: fetch time minus
  notification time over the last 24 hours (target under 300).
- `completeness`: per resource, `missing` (stored items without a row, only meaningful when `expected` is true, that
  is when the resource is in `bundle_resources`) and `non_2xx` by status code.
- `counters`: stale discards, suppressed noise and ML requests per endpoint family with `requests_429`, cumulative
  since the ML worker started.
- `events`: counts per type (24 h and 7 d) and the age of the newest event. `links`: `enabled` and the coverage
  report of the product links. `top_changed_paths`: the most frequent changed paths of the last 7 days (candidates
  for the excluded-noise list).
- `sections_failed`: a section that failed or timed out is null and named here; the rest still answers.

### Notes

- `POST /enqueue` is accepted while `refresh.enabled` is off, the entries wait and the answer says so
  (`refresh_enabled: false`). `missing_from_bundle_resources` lists the named resources that `bundle_resources` does
  not include (the refresh handler would drop them).
- The request does not send any wake-up: the worker picks the `requested` mark up on its next pass. A request made
  while the handler is off is kept and honored once it is on.
- Rollback: `PUT /settings/<flag>` with `{"value": false}`, or `ML_PUB_KILL_SWITCH=1` and a restart.
