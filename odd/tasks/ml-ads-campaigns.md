# ML Product Ads campaigns: persist the catalog and the daily metrics

## Objective

Persist the Product Ads campaigns that `campaigns/search` already returns on every ads day (today only its
`metrics_summary` is kept in `ml_ads_day_ledger`). Owner rule: persist ALL of ML's data. Matching brand
contributions to campaigns is the owner's team's job later and is out of scope.

## Scope

- One Alembic migration: `ml_ads_campaigns` (latest catalog per advertiser + campaign) and
  `ml_ads_campaign_days` (one row per advertiser + campaign + day with that day's metrics).
- Fields come from the captured response (`tests/fixtures/ml_ads/campaigns_summary_2026_10_05.json`, already a
  real one-day capture); no new fixture file.
- Ingestion: the SAME `campaigns/search` call of the day pipeline (`_read_summary`, used by both the day fetch and
  the D-4..D-14 verify) persists its `results`. Extra pages only when `paging.total` exceeds the first page.
- Out of scope: board/KPI subtraction, Ventas ML, order_metrics, frontend, brand contribution fields.

## Constraints

- No new cron, worker or derived table; no request change to the closing summary call.
- Facts are keyed by the REPORTING advertiser (mapper rule ADS-3), never the payload's `advertiser_id`.
- No column named like a cached sum (`total_amount` stays in `raw`).
- About 400 authored lines per PR; never `size:exception`.

## Tasks

Delivery: `stacked-to-main`, slices of about 400 authored lines (the whole change measured ~500 with tests).

- [x] T1 (PR A) Migration + models for `ml_ads_campaigns` and `ml_ads_campaign_days`, migration test
  (route: inline; one coherent backend slice already mapped).
- [x] T2 (PR B) Mapper + store: catalog upsert (latest), day upsert, drop the day rows of campaigns ML no
  longer lists.
- [x] T3 (PR B) Ingestion: persist from `_read_summary`, read extra pages when `paging.total` says so.
- [ ] T4 (PR C) Backfill of days already closed (see Next slice).

## Acceptance criteria

- A replayed 25713 day stores 16 campaigns and 16 day rows whose costs add up to ML's day total (614,060.07).
- A listing longer than its first page is read to the end; every campaign is stored.
- A campaign ML stops listing for a day loses that day's row; its catalog row stays.
- Migration upgrades and downgrades cleanly; single alembic head.

## Checks

- `pytest tests/services/ml_ads tests/workers/handlers/test_ml_ads.py` with the private Postgres test DB.
- `uvx ruff@0.15.1 format app/ tests/ alembic/` and `uvx ruff@0.15.1 check app/`.

## Backfill slice (PR C)

Backfill of campaign days for days already closed in the ledger (D-15..D-90 are `final` and never re-read):
a `campaigns` ledger source run through `schedule._run_account_level`, one `campaigns/search` per day.

## Progress

- PR A, branch `feat/ml-ads-campaigns` from origin/main: T1. RED observed (4 migration tests failing before the
  migration/models existed), GREEN after; alembic stamp/upgrade/downgrade/upgrade checked on a scratch DB.
- PR A #1592 merged (merge commit `3f38a2dc`).
- PR B, branch `feat/ml-ads-campaigns-ingest-2` from origin/main (A's commits dropped): T2-T3 in `aad727ab`
  (store + ingestion) and `ad0bac2f` (a campaign repeated across listing pages is kept once; upserting it twice
  in one statement failed in Postgres and stopped the day from closing). RED observed on main without B's code
  (6 failed: `map_campaigns` missing, 0 rows stored) and for the repeated campaign (CardinalityViolation), GREEN
  after; focused suites `tests/services/ml_ads` + `tests/workers/handlers/test_ml_ads.py`: 267 passed. Alembic
  untouched by B.

## Next step

PR C (T4): backfill of the closed days D-15..D-90.
