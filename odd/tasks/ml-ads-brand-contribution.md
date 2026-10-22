# ml-ads-brand-contribution

Objective: let the team load brand contributions to Product Ads campaigns (percentage or fixed amount over a date range) so Métricas ML stops subtracting the part of the campaign cost the brand pays.
Branch: `feat/ml-ads-brand-contribution-api` (PR1), then one branch per PR. Delivery: `stacked-to-main` (each PR closed and safe to merge alone). Test runner: `pytest` (backend), `vitest` (frontend, PR3).

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
| T1b-i | S4 (create), S7 | delegated writer | PR open (this branch) | `628288c8a` (+377/-13); RED 17 failed, GREEN 54 passed |
| T1b-ii | S4 (edit, delete) | delegated writer | local `feat/ml-ads-brand-contribution-edit`, opens after T1b-i merges | ~+138/-9; RED 6 failed, GREEN 357 passed (ml_ads scope) |
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
