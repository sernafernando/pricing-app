# ml-ads-brand-contribution

Objective: let the team load brand contributions to Product Ads campaigns (percentage or fixed amount over a date range) so Métricas ML stops subtracting the part of the campaign cost the brand pays.
Branches: `feat/ml-ads-brand-contribution-api` (T1a, merged #1704), `feat/ml-ads-brand-contribution-create` (T1b-i, #1706), `feat/ml-ads-brand-contribution-edit` (T1b-ii), then one branch per PR. Delivery: `stacked-to-main` (each PR closed and safe to merge alone). Test runner: `pytest` (backend), `vitest` (frontend, PR3).

## Specs

- **S1** (user, L1): "sí, porque hay campañas que tienen aporte de las marcas y para eso necesitamos el desglose de campañas, porque si tiene aporte de la marca no descontarían del total o no el 100%". The campaign cost that a brand contribution covers is not subtracted from Total Gauss.
- **S2** (user, L2): "no pierdas el tiempo, eso lo vamos a matchear nosotros". Contributions are loaded by hand per campaign; no automatic matching of campaigns to brands.
- **S3** (user, L3 + L4): "puede ser % o monto fijo"; "rango de fechas que cargamos nosotros". A contribution is a percentage or a fixed amount, over a date range the team loads.
- **S4** (decision by the assistant, not a user quote): a contribution = (`advertiser_id`, `campaign_id`, `kind` in {`percentage`, `fixed_amount`}, `value`, `date_from`, `date_to` inclusive, optional `brand` and `note` text, created/updated by user plus timestamps). Several contributions per campaign are allowed; overlapping ranges of the same campaign are rejected (422). The campaign must exist in `ml_ads_campaigns` (422 otherwise).
- **S5** (decision by the assistant): `percentage` (0 < p <= 100) reduces each day's subtracted cost of that campaign within the range by p%.
- **S6** (decision by the assistant): `fixed_amount` (> 0, money with 2 decimals) is spread over the range's days in proportion to each day's campaign cost (from `ml_ads_campaign_days`), never exceeding that cost (the contribution of a day is capped at the day's cost).
- **S7** (decision by the assistant): permissions reuse the project's system. Viewing uses the existing `ml_metricas.ver_ganancia`; creating, editing and deleting use the new `ml_metricas.gestionar_aportes_ads`, seeded for ADMIN only by migration (same pattern as `sell_out.gestionar`).
- **S8** (PR1 scope, split into T1a read + T1b write): storage, permission and API only (list campaigns with their contributions and their cost in a range; create, update, delete). No Métricas ML number changes in PR1.
- **S9** (PR2, not in PR1): the Métricas ML board and KPI subtraction of Product Ads (`publicidad=mla|todo`) honours S5 and S6.
- **S10** (PR3, not in PR1): a frontend page to load contributions, the contribution shown in the Ads block, and its `novedades` entry.

## Tasks

| ID | Specs | Route | Status | Commit / evidence |
|----|-------|-------|--------|-------------------|
| T1a | S4 (storage), S8 (read) | delegated writer | merged (#1704) | `96faa8862` (+450/-3); RED 4 failed + 7 errors, GREEN 39 passed |
| T1b-i | S4 (create), S7 | delegated writer | merged (#1706) | `628288c8a` (+377/-13); RED 17 failed, GREEN 54 passed |
| T1b-ii | S4 (edit, delete) | delegated writer | PR open (rebased after the #1708 heads merge) | ~+262/-12 incl. pins; RED 6 failed (+2 mutation REDs for pins), GREEN 24 passed in the write+concurrency files |
| T2 | S5, S6, S9 | pending | pending | PR2 |
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
