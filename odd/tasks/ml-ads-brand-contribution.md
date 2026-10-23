# ml-ads-brand-contribution

Objective: let the team load brand contributions to Product Ads campaigns (percentage or fixed amount over a date range) so Métricas ML stops subtracting the part of the campaign cost the brand pays.
Branches: `feat/ml-ads-brand-contribution-api` (T1a, merged #1704), `feat/ml-ads-brand-contribution-create` (T1b-i, #1706), `feat/ml-ads-brand-contribution-edit` (T1b-ii), then one branch per PR. Delivery: `stacked-to-main` (each PR closed and safe to merge alone). Test runner: `pytest` (backend), `vitest` (frontend, PR3).

## Specs

- **S1** (user, L1): "sí, porque hay campañas que tienen aporte de las marcas y para eso necesitamos el desglose de campañas, porque si tiene aporte de la marca no descontarían del total o no el 100%". The campaign cost that a brand contribution covers is not subtracted from Total Gauss.
- **S2** (user, L2): "no pierdas el tiempo, eso lo vamos a matchear nosotros". Contributions are loaded by hand per campaign; no automatic matching of campaigns to brands.
- **S3** (user, L3 + L4): "puede ser % o monto fijo"; "rango de fechas que cargamos nosotros". A contribution is a percentage or a fixed amount, over a date range the team loads.
- **S4** (decision by the assistant, not a user quote): a contribution = (`advertiser_id`, `campaign_id`, `kind` in {`percentage`, `fixed_amount`}, `value`, `date_from`, `date_to` inclusive, optional `brand` and `note` text, created/updated by user plus timestamps). Several contributions per campaign are allowed; overlapping ranges of the same campaign are rejected (422). The campaign must exist in `ml_ads_campaigns` (422 otherwise).
- **S5** (decision by the assistant): `percentage` (0 < p <= 100) reduces each day's subtracted cost of that campaign within the range by p%.
- **S6** (user, L10 + decisions by the assistant): "hay que poder elegir en la campaña si el monto es fijo y se recibe todo o si no supera ese monto se devuelve la diferencia". A `fixed_amount` carries `settlement` in {`full`, `refund_difference`}, chosen when it is loaded (on the contribution, since one campaign can have several ranges):
  - `full` ("se recibe todo"): the brand pays the whole amount whatever the campaign spent; any amount above the range's spend is income, not lost.
  - `refund_difference` ("si no supera ese monto se devuelve la diferencia"): the contribution counts only up to the range's spend; the rest goes back to the brand.
  - Spread (assistant): the counted amount is spread over the range's days in proportion to each day's campaign cost (`ml_ads_campaign_days`); for `refund_difference` that never exceeds a day's cost. `percentage` has no `settlement` (NULL). Rows stored before L10 are backfilled `refund_difference` (never overstates profit).
- **S7** (decision by the assistant): permissions reuse the project's system. Viewing uses the existing `ml_metricas.ver_ganancia`; creating, editing and deleting use the new `ml_metricas.gestionar_aportes_ads`, seeded for ADMIN only by migration (same pattern as `sell_out.gestionar`).
- **S8** (PR1 scope, split into T1a read + T1b write): storage, permission and API only (list campaigns with their contributions and their cost in a range; create, update, delete). No Métricas ML number changes in PR1.
- **S9** (PR2, decisions by the assistant from the T2 map, 2026-10-23): the Métricas ML board and KPI subtraction of Product Ads (`publicidad=mla|todo`) honours S5 and S6. Rules:
  - Applied once, in `Board._ads_source` (`board_ads_lines`), so board rows, groups, Total Gauss, markup, the comparison period, "Sin producto", the KPI Ads block and the CSV all follow.
  - A campaign's day cost is the sum of its `ml_ads_item_days.cost` rows (what the board subtracts), keyed by the item row's (`advertiser_id`, `campaign_id`, `day`); not `ml_ads_campaign_days.cost`, so the contribution removes exactly its share of what the board shows.
  - `percentage`: each item row of the campaign inside the range contributes cost × p/100.
  - `fixed_amount`: the counted amount (`full`: the whole amount; `refund_difference`: min(amount, the campaign's spend over the whole contribution range)) is spread over the range's days and that campaign's item rows in proportion to their cost, using the whole range (not only the board period). For `full` above spend a row's contribution can exceed its cost, so its ads cost goes negative and Total Gauss rises. A range with zero spend has nothing to spread over and contributes nothing on the board.
  - Item rows with no campaign (NULL or 0) get no contribution.
  - The KPI Ads block keeps ML's gross cost (`cost_api`/`cost_total`) and the subtracted figures go net of contributions; the contribution total is exposed as its own field for T3.
  - Out of scope: sparklines (already before ads), the Publicaciones view and `/ml-ads/by-mla|by-product` (they read `read.py`, not the board).
- **S10** (PR3, not in PR1): a frontend page to load contributions, the contribution shown in the Ads block, and its `novedades` entry.

## Tasks

| ID | Specs | Route | Status | Commit / evidence |
|----|-------|-------|--------|-------------------|
| T1a | S4 (storage), S8 (read) | delegated writer | merged (#1704) | `96faa8862` (+450/-3); RED 4 failed + 7 errors, GREEN 39 passed |
| T1b-i | S4 (create), S7 | delegated writer | merged (#1706) | `628288c8a` (+377/-13); RED 17 failed, GREEN 54 passed |
| T1b-ii | S4 (edit, delete) | delegated writer | merged (#1709) | ~+262/-12 incl. pins; RED 6 failed (+2 mutation REDs for pins), GREEN 24 passed in the write+concurrency files |
| T1c | S6 (settlement storage + API) | inline | PR open | RED 13 failed + 8 errors, GREEN 77 passed; migration suites 154 passed |
| T2 | S5, S6, S9 | delegated writer (context backstop: long parent session) | GREEN, needs volume DDL line | branch `feat/ml-ads-contribution-board`, stacked on T1c; see Log 2026-10-23 T2 |
| T3 | S10 | pending | pending | PR3 |

## Log

- **L1** (2026-10-16, user): "sí, porque hay campañas que tienen aporte de las marcas y para eso necesitamos el desglose de campañas, porque si tiene aporte de la marca no descontarían del total o no el 100%"
- **L2** (2026-10-16, user): "no pierdas el tiempo, eso lo vamos a matchear nosotros"
- **L3** (2026-10-22, user, asked whether a fixed % per campaign or a monthly amount): "puede ser % o monto fijo"
- **L4** (2026-10-22, user, asked whether the fixed amount is over a date range they load or per calendar month): "rango de fechas que cargamos nosotros"
- **L5** (2026-10-22): plan of 3 stacked PRs (storage+API, board/KPI, frontend). T1 started on `feat/ml-ads-brand-contribution-api` off `origin/main`.
- **L6** (2026-10-22): T1 GREEN. Table `ml_ads_campaign_contributions` (CHECKs kind/value/dates, index advertiser+campaign; audit ids without FK so `ml_ads_*` stays self-contained), permission `ml_metricas.gestionar_aportes_ads` ADMIN only, endpoints `GET /ml-ads/campaigns`, `POST /ml-ads/contributions`, `PUT|DELETE /ml-ads/contributions/{id}`. Overlap and catalogue checks lock the campaign row (`FOR UPDATE`). One PR (~440 production + ~390 test lines): splitting storage from API would ship a permission that gates nothing. Next: T2.
- **L7** (2026-10-22, coordinator): #1704 was +861/-13; the owner's rule is each PR <= ~400 authored lines including tests, never `size:exception`. Split by read/write: T1a = table + model + read-only `GET /ml-ads/campaigns` (ver_ganancia); T1b = second migration seeding `ml_metricas.gestionar_aportes_ads` for ADMIN + POST/PUT/DELETE, stacked on T1a, pushed only after T1a merges. Full original kept on local branch `wip/ads-contrib-full` (046e83ea2).
- **L8** (2026-10-22, coordinator): T1a approved at 446 (~410 without the doc), merged as #1704. T1b split into T1b-i (permission migration + POST with validation and overlap lock) and T1b-ii (PUT/DELETE + delete logging), stacked; T1b-i rebased on main and opened.
- **L9** (2026-10-22, coordinator): independent verifier passed #1706 with no blockers; its advisories land in T1b-ii: per-user override pins on POST (granting override 201, revoking override on ADMIN 403, manage without ver_ganancia 403) and a two-session Postgres pin that an overlapping load on a locked campaign waits and is rejected while another campaign does not wait. Regression pins: the behaviour already existed; RED shown by mutation (dropping `with_for_update` fails the wait pin; dropping the manage dependency fails the revoking-override pin).
- 2026-10-23: #1706 merged; #1706 and #1707 left two alembic heads, joined by the empty merge revision #1708 (merged). T1b-ii rebased on main: focused files 53 passed, single-head tests 5 passed, ruff clean.
- 2026-10-23: GGA observations fixed in the same PR: edit/delete lock the contribution row first (an edit racing a delete is 404, was a 500 StaleDataError), and an edit cannot move a contribution to another campaign (422 on campaign_id). RED 2 failed, GREEN 54 passed.
- **L10** (2026-10-23, user, asked whether fixed-amount surplus is lost or shown as unused): "hay que poder elegir en la campaña si el monto es fijo y se recibe todo o si no supera ese monto se devuelve la diferencia"
- 2026-10-23: #1709 merged (ancestor of origin/main verified). L10 reopens S6: new task T1c (migration adding `settlement` + API field) before T2.
- 2026-10-23: T1c GREEN on `feat/ml-ads-contribution-fixed-settlement`: migration `20261116_ml_ads_contribution_settlement` (nullable `settlement`, backfill fixed rows `refund_difference`, CHECKs values + kind), ORM, API field required for fixed amounts and rejected for percentages. Risk item 1 (migration with backfill) -> independent verifier.
- 2026-10-23: T1c opened as #1713 (verifier: no blockers). T2 mapped (explorer): single application point `Board._ads_source`; S9 rules recorded above as assistant decisions. T2 delegated to one writer on `feat/ml-ads-contribution-board`, pushed only after #1713 merges.
- 2026-10-23 (T2 writer): contributions computed per item row in the `board_ads_lines` statement (CTE `ads_contribution_spend` = each overlapping fixed amount's whole-range spend); `board_ads_lines.contribution` beside the gross `cost`; pair `ads`/`prev_ads` net of it, `ads_cost_api` gross, new pair column `ads_contribution`; KPI `cost_api`/`cost_total` gross, `subtracted_total` net, new `contribution` (AdsKpis + KpiAds). No new statement. RED: 7 failed + 1 passed (the NULL/0 campaign guard) in `test_board_ads_contributions.py`; the PG numeric pin and the CSV pin written after GREEN fail against the base code (9 failed with base `board.py`/`kpi_strip.py`). GREEN: 9 passed; ads + export files 167 passed with the volume DDL line below. Blocker outside the T2 surface: `test_board_volume_postgres.py` temp `ml_ads_item_days` lacks `campaign_id` (8 errors, UndefinedColumn); fix = append `, campaign_id BIGINT` to its DDL (verified: 52 passed incl. the fixed statement count).
- 2026-10-23: independent verifier on T2: S5/S6 pass, invariants pass (no contributions = byte-identical output; 1000 spread over 98 rows exact to the cent; statement count unchanged). Blocker B1 fixed: "solo con ventas" kept rows by NET ads, so a contribution taking them to <= 0 hid the row and its income left Total Gauss while the KPI Ads block kept it; now it reads ML's gross `ads_cost_api` (carried into row and group sums). RED 2 failed (full above spend, 100%), GREEN; board ads + volume + export + groups suites 200 passed.
