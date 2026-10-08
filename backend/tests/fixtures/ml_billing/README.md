# ML billing fixtures

Source: the real capture `billing_balance_capture_20261007_123428.json.gz`
(taken 2026-10-07 from the ML billing API through the proxy, general
`/details`, `document_type=BILL`, period `2026-09-01`, `from_id` paging,
`limit=1000`, `sort_by=ID`, `order_by=ASC`). Nothing is invented and nothing
is stripped: `payer_nickname`, `state_name`, `marketplace_info` and
`currency_info` are kept as ML sent them.

## `general_bill_2026_09_01_pages.json.gz`

All 35 pages of the 2026-09-01 BILL sweep, in order, from
`ml.details.general_BILL["2026-09-01"].pages`. Each page keeps ML's own
envelope fields (`status`, `total`, `offset`, `limit`, `last_id`,
`n_results`) plus `detail_ids`: the real `charge_info.detail_id` of each row
on that page, taken from `ml.details.general_BILL["2026-09-01"].rows`
(33,210 rows, partitioned by `n_results`).

What the pages prove:

- `total` is the number of rows REMAINING after the cursor, not the size of
  the period: 33260, 32260, ... 310, 0.
- Two short pages (950 rows with `limit=1000`, pages 16 and 29) are NOT the
  end: the next page continues from `last_id`.
- Page 33 is a final partial page (310 rows) and page 34 is the empty page
  (`last_id=0`) that really ends the pass.

The full row bodies (about 50 MB) are not committed. Tests that replay the
whole sequence build each row body from a real row in the sample file below
with the page's real `detail_id` substituted. The paging behavior under test
depends on ids and counts only.

## `general_bill_2026_09_01_sample_rows.json`

Seven complete rows, copied verbatim from
`ml.details.general_BILL["2026-09-01"].rows`: sub-types CVFV (two, with
`payer_nickname` and `state_name`), BVFV (BONUS), BPAD (BONUS), CXD, CSSTEC
and PADS (no `items_info` and no `sales_info`). Every row carries
`marketplace_info` and `currency_info`.
