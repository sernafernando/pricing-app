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

## `documents_2026_09_01.json` (PR 2b)

Source: the same capture, `ml.documents.BILL.results` (2 documents:
5140824542 and 5140811928) and `ml.documents.CREDIT_NOTE.results` (5
documents), period `2026-09-01`, requested as
`/documents?group=ML&document_type=...`. Copied verbatim, nothing stripped:
`amount`, `unpaid_amount`, `count_details`, `associated_document_id` and
`files[].reference_number` (`0058A00975220`, `0001A03750426`, ...) are ML's own.
The capture stored the response list under `results`.

## `general_bill_2026_09_01_document_rows.json.gz` (PR 2b)

A projection, not a copy, of `ml.details.general_BILL["2026-09-01"].rows`: for
each of the 33,210 real rows only `[detail_id, document_info.document_id,
charge_info.detail_type, charge_info.detail_amount]`, in capture order. It is
the "silent row loss" data set of the capture: 26,020 rows for document
5140824542 and 7,190 for 5140811928, i.e. 36 and 14 rows short of the
documents' `count_details` (26,056 / 7,204). With the mapper's sign rule
(`BONUS` negated) the rows sum to 533,291,421.83 and 56,558,466.41, against
the documents' 534,258,231.37 and 56,674,709.86.

The 50 rows ML never returned are not in the capture. The tests that need the
COMPLETE documents add 36 + 14 rows synthesized in the test, whose amounts are
exactly the difference to the document totals (966,809.54 and 116,243.45).
That is a stand-in for the missing rows and is the only invented data here.

## `captured_400_envelope.json`

The bare 400 ML answers on an intermittent poison page, copied verbatim from
`flex_billing_capture_20261007_145424.json`
(`flex_details["2026-09-01:CREDIT_NOTE"]`, second 400 entry, `body`). It has no
`error` field and no cause: `status`, `type: BAD_REQUEST_ERROR`, a generic
`message` and the request `path`. The same envelope was seen for 2026-10-01
and, on the general `/details` with `from_id` paging, in
`billing_balance_capture_20261007_123428.json.gz`. Nothing is edited.

## `captured_flex_offset_pages.json` (PR 4a-iv)

Source: `flex_billing_capture_20261007_150559.json`, `flex/details`,
`document_type=CREDIT_NOTE`, period `2026-10-01`, offset paging, `limit=500`.
Per page, ML's own `offset`, `limit` and `total` plus the real `n_results`, and
the first 12 real `detail_id`s of page 0. It proves the offset shape: pages are
contiguous (`offset` 0, 500, ... 3000), the last one is partial (325) and
`total` drifts while the sweep runs (3324 -> 3325).

## `credit_note_2026_09.json.gz` (PR 4b)

Source: the same capture, `ml.details.general_CREDIT_NOTE["2026-09-01"]`
(general `/details`, `document_type=CREDIT_NOTE`, `from_id` paging,
`limit=1000`). The two real pages in order, each with ML's own envelope
(`total`, `limit`, `offset`, `last_id`, `n_results`) and its `results`: the
196 complete rows (nothing stripped; `payer_nickname`, `state_name`,
`marketplace_info`, `currency_info` and `charge_bonified_id` as ML sent them)
and the empty page (`last_id=0`) that ends the pass. The 5 credit-note
documents these rows belong to are in `documents_2026_09_01.json`.

What the rows prove: all 196 are `detail_type=BONUS` (sub-types BVFV 100, BXD
36, BVFF 25, BVFN 19, BFF 8, BSSTEC 3, BIBME 2, BIB 2, BS 1); 195 carry a
`charge_bonified_id` and the one that does not is the `BS` row of 8,675,215 (a
whole-document reversal, document 5224932860); none of the 196 `detail_id`s
and none of the 195 `charge_bonified_id`s is among the period's 33,210 BILL
`detail_id`s, i.e. credit notes reverse invoices of EARLIER periods.

## `periods_bill.json` (PR 4c-ii)

Source: the same capture, `ml.periods.BILL.body`: ML's first `monthly/periods?group=ML`
page as sent (`limit` 12, `total` 13): the OPEN period 2026-10-01 and the 11 CLOSED
ones 2026-09-01 .. 2025-11-01. The lap walks exactly these 12.

## `flex_rows.json` (PR 5-i)

Four complete flex detail rows, copied verbatim, nothing stripped (receiver and
buyer nicknames included):

- `bflx_599` and `bflx_8990`: the `matches[]` of `flex_billing_capture_20261007_150559.json`
  (`flex/details`, `CREDIT_NOTE`, period 2026-10-01): BFLX for orders
  2000018846584294 (599) and 2000018808335864 (8,990), both `PROCESSING`.
- `cflx_reciprocal` (`BILL`) and `bflx_reciprocal` (`CREDIT_NOTE`): period
  2026-09-01 rows of `billing_balance_capture_20261007_123428.json.gz`
  (`ml.details.flex_BILL` / `flex_CREDIT_NOTE`), detail ids 69348178279 and
  69346475478; each one's `detail_associated_id` is the other's `detail_id`.

What the capture shows: none of the 13,688 flex rows (773 CFLX in BILL, 12,915
BFLX in CREDIT_NOTE) has `items_info`; the order is `shipping_info.order.order_id`.
Their `detail_id`s do not overlap the 33,406 general ones.
