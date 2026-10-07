# ML publications scan: first backfill and routine laps

The scan handler (`ml_publications.scan`) enumerates every seller item per status with
`GET /users/{seller}/items/search?search_type=scan` and the returned `scroll_id`. It is inert until
`scan.enabled` is turned on, and it runs on the existing `pricing-worker-ml` worker: a daily slot at
03:30 (Argentina) plus a 30 s catch-up while a lap is unfinished. No cron, timer or LISTEN/NOTIFY is involved.

Run every command from `backend/` (so the `.env` is found).

## What a lap does

| Mode | When | Effect |
|---|---|---|
| `full` | requested with `--mode full`, or the store is empty | every enumerated item is enqueued in the backfill lane (3) |
| `rescan` | otherwise | an item is enqueued in the reconcile lane (2) only if it is missing, gone, last checked more than `ML_PUB_STALE_DAYS` (7) ago, or its status differs |

* Statuses are scanned in the order of `scan.statuses`; the default is
  `closed,paused,under_review,inactive,pending,active`. `closed` is first because closed items vanish fast
  (39 on 2026-10-06). Totals that day: active 7,789, paused 16,185, pending 650.
* The scan status and the item body status are different vocabularies: the `pending` scan returns items whose
  body status is `inactive`; the rescan comparison goes through that map, so those items are not re-enqueued
  on every lap.
* Valid statuses: `active`, `paused`, `closed`, `under_review`, `inactive`, `pending`.
* An empty status (`scroll_id: ""`, `total: 0`) completes at once. A `400` on the first request marks the
  status `unsupported` and the lap goes on. A scroll that expired (about 5 minutes) restarts that status, at
  most 3 times, then the status is recorded as failed for the lap.
* After a lap, stored items that no scan returned get a direct refresh (never a delete). Closed items drop out
  of the scans while ML still answers 200 for them, so an unseen `closed` item is refreshed only once it is
  older than `ML_PUB_STALE_DAYS`, not on every lap.
* Progress lives in `ml_pub_scan_state` (one row per status plus the `_lap` row) and one `ml_pub_job_runs` row
  per lap. A restart resumes from the stored scroll.

## First backfill

The backfill fetches only the item core: keep `bundle_resources` at `["core"]` (about 25k items, about 250 scan
pages plus about 1,240 `/items/bulk` calls, under 15 minutes at 2 req/s, lane 3). The refresh handler must be
enabled too, or the entries only wait in the queue.

1. `python -m app.scripts.ml_publications_settings get bundle_resources` must print `["core"]`.
2. `python -m app.scripts.ml_publications_settings set refresh.enabled true`
3. Closed items first (they vanish fast):
   `python -m app.scripts.ml_publications_settings set scan.statuses '["closed"]'`
   `python -m app.scripts.ml_publications_settings set scan.enabled true`
   `python -m app.scripts.ml_publications_request ml_publications.scan --mode full`
4. Watch it finish: `SELECT status, pages, enumerated, enqueued, restarts, unsupported, completed_at, last_error
   FROM ml_pub_scan_state;` (the `_lap` row is the lap itself) and `SELECT * FROM ml_pub_job_runs ORDER BY id DESC
   LIMIT 1;` (outcome `success`).
5. Then every status: `python -m app.scripts.ml_publications_settings set scan.statuses
   '["closed","paused","under_review","inactive","pending","active"]'` and run
   `python -m app.scripts.ml_publications_request ml_publications.scan --mode full` again.
6. Check: every enumerated item reaches `ml_items` (`SELECT count(*) FROM ml_items;` close to 24.7k), the queue
   drains (`SELECT lane, count(*) FROM ml_pub_refresh_queue GROUP BY lane;`), and `pending` items stored with
   body status `inactive` are not re-enqueued by the next rescan.

`--mode full` is consumed (back to `rescan`) when that lap completes, even if a status failed: check the lap record
(`outcome = failed`, `last_error`) and request it again after fixing the cause. A full request made while a lap that is
already full is running (for example the first lap of an empty store) is satisfied by that lap: it is consumed
when that lap ends, it does not start another one. `--mode rescan` cancels a full request that
has not started.

## Pause and rollback

* Pause: `python -m app.scripts.ml_publications_settings set scan.enabled false`. The scan stops at the next page
  boundary and keeps its progress; turning the flag on again resumes the same lap.
* Rollback: the same command. Nothing is deleted by the scan, and the queued entries are still served by the
  refresh handler (turn `refresh.enabled` off to stop the fetches as well).
* A request made while the flag is off stays pending and is honored once the flag is on.
* Missing setup: with no `ML_USER_ID`, no ML credentials or a rejected token (`seller_not_configured`,
  `not_configured`, `no_token`, `unauthorized`) the run reports `blocked` in `worker_job_state.detail`, ends as
  finished and falls back to the daily 03:30 slot instead of retrying every 30 s. That run also consumes a
  pending request; `scan.next_mode = full` is kept, so fix the setup and request the scan again to run it now.
  Five failing runs of the same kind with no successful run in between end the same way: `blocked = upstream_error` for a sustained ML outage,
  `internal_error` when the failures are unexpected exceptions of the scan itself.
