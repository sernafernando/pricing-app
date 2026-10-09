# ML Ads fixtures (ml-billing-balance PR 1b)

Every replayed response is a real captured ML body. No value was edited, renamed or removed inside any
captured object; only whole responses were selected and re-wrapped (listed below). Nothing is trimmed:
the files are gzipped instead. Do not hand-write fixtures here: a hand-made shape is an assumption about an
API we do not own. Tests that perturb a body (for example to force a mismatch) deep-copy a real one in the
test and say so; they do not add replay data.

Sources (read-only, outside the repo, under `pricing-app-worktrees/ml-captures/`):

- `ads_fullday_capture_2026-10-05_20261008_111621.json.gz` ("full-day capture", day 2026-10-05, captured 2026-10-08)
- `ads_probe_capture_20261007_192336.json.gz` ("probe"): kept only for the per-date series below
- `ads_capture_20261007_214456.json` ("window capture", 2026-09-07..2026-10-06): kept only for the moved group and the advertisers list

The full-day capture supersedes the probe for the day pipeline: the probe kept full group rows only for the
72 cost-bearing groups and drilled only 5 of them, so it needed placement and synthetic pages. The full-day
capture has every page of the day and every `/ads` page of every cost-bearing group.

| File | Source | What it is |
|------|--------|------------|
| `groups_day_2026_10_05_25713.json.gz` | full-day, `advertisers.25713.group_pages` | The 28 `ad_groups/search` responses (`request`, `status`, `body`) of advertiser 25713: offsets 0..5400, limit 200, total 5,540, all 5,540 rows. 72 have cost > 0, 19 more have activity with cost 0 (organic units). |
| `groups_day_2026_10_05_714700.json.gz` | full-day, `advertisers.714700.group_pages` | The 2 responses (total 338, all rows) of advertiser 714700, a day with zero spend. |
| `ads_day_2026_10_05_25713.json.gz` | full-day, `advertisers.25713.ads_pages` | Group id -> `/ads` responses for the 72 cost-bearing groups: 82 pages, all of them (limit 50). Per-ad costs add up to 614,060.07, and to each group's own cost. |
| `campaigns_summary_2026_10_05.json` | full-day, `advertisers.*.campaigns_day` | `campaigns/search` with `metrics_summary`: 25713 cost 614,060.07; 714700 cost 0. |
| `requests_2026_10_05.json` | full-day, `calls` | The 114 one-day product_ads requests really sent (path, params, `api_version`, status), all 200 on Api-Version 2: 2 summaries, 30 group pages, 82 `/ads` pages. The 3 version-check calls and the per-date calls are excluded. |
| `api_version_check_2026_10_05.json` | full-day, `calls` (`limit=1`) | The same one-day `campaigns/search` sent with no `Api-Version` header, 1 and 2: all three answered 200. Only the request records are kept, not the bodies. |
| `advertisers_pads.json` | window capture, `advertisers.PADS` | The real `GET /advertising/advertisers?product_id=PADS` answer (status, path, params, body): advertisers 714700 and 25713. |
| `ads_daily_series_group_953712626.json` | probe, `top_groups[0].ads_week_daily` | A real `aggregation_type=daily` answer: a per-date series with no item identity (ADS-1). |
| `display_day_2026_10_05_25713.json` | full-day, `display` + `calls` | The real Display answers of advertiser 25713 for 2026-10-05 (PR 3): the `display/campaigns` list (7 campaigns) and each campaign's one-day `metrics` response, with the request (path, params, `api_version` 1) that was sent. 4 campaigns spent (121,938.82 in all), 3 have no row for the day. |
| `brand_ads_day_2026_10_05.json` | full-day, `brand_ads` + `calls` | The real Brand Ads answers of both advertisers (714700, 25713) for 2026-10-05 (PR 3-iii), each with the request (path, params incl. `aggregation_type=daily`, `api_version` 1) that was sent. Every figure is zero that day: the non-zero mapping is covered only by the structure of this shape. |
| `moved_group_2678077237.json` | window capture, `pads.714700` | The revoked/moved group (advertiser 714700, original 25713) and its 30 ads page. |

## Facts a replay relies on (verified against the capture)

- Two groups (953674183, 985516160) have exactly 50 ads. The capture also holds their `offset=50` page (empty
  `results`, `total` 50); ingestion reads `paging.total` and never requests it, so 80 of the 82 pages are requested.
- Zero-cost group rows of the day are real: 19 groups have cost 0 and organic units > 0 (stored, never drilled);
  the other 5,449 rows have no activity and produce no fact.
- Group 953712626: 33 ads, 64,692.18. Group 953639148: 66 ads in 2 pages, 36,647.80. Group 953635388: 57 ads in 2 pages, 31,770.10.
- The window capture's `moved_group` is a 30-day figure for a different advertiser; it only exercises the keying
  rule (facts belong to the REPORTING advertiser) and is not part of any day replay.
- Request headers were recorded this time (`api_version` per call), so the `Api-Version` values are captured, not assumed.

Display is copied (PR 3-i) and so is Brand Ads (PR 3-iii); its cost lives in `dashboard.consumed_budget[{x,y}]`
(all zeros that day).
