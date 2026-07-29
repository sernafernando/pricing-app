# Exploration — productos-costo-ppp

Informational PPP (weighted average cost, "precio ponderado") in the Productos list:
show it under the existing cost, and show a derived `ppp: n%` line under each markup.
The current pricing method (based on the list cost) does not change.

## Current state (verified)

- `Producto.costo` / `Producto.moneda_costo` — `backend/app/models/producto.py:23-24`, populated from
  `coslis_price` in `backend/app/api/endpoints/productos_sync.py:58`. This is a **cost list** price.
- `backend/app/models/item_cost_list.py` and `item_cost_list_history.py` replicate ERP cost **lists**
  (`comp_id`, `coslis_id`, `item_id`, `coslis_price`, `curr_id`) — not weighted averages.
- All markups displayed in the productos list (clasica, rebate, oferta, web_real, 3/6/9/12 cuotas,
  pvp + pvp cuotas) are computed backend-side in `backend/app/api/endpoints/productos_listing.py`
  (~900-1210) through `calcular_markup(limpio, costo)`
  (`backend/app/services/pricing_calculator.py:340` — `(limpio / costo) - 1`).
  `limpio` (net proceeds) does **not** depend on which cost basis is used.
- `ProductoPricing.markup_calculado` / `markup_rebate` / `markup_oferta` / `markup_web_real` are
  **stored** columns backing SQL list filters (`productos_listing.py:492-511`). A display-only PPP
  markup does not need to be stored.
- Frontend: `frontend/src/pages/Productos.jsx` (3111 lines; CRLF historically, now forced to LF by
  `.gitattributes`).
  - Cost cell: line 1715 — `<td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>`
  - Markup render spots (12): 1765, 1772 (clasica; offset span 1774-1785), 1933 (mejor oferta),
    2044 (web_real), 2096 / 2129 / 2162 / 2195 (3/6/9/12 cuotas), 2235 / 2270 / 2305 / 2340 (pvp cuotas)
  - Helpers: `getMarkupColor`, `useProductosOffsets.js` (imported at line 140).

## Source of truth for PPP (verified, high confidence)

`ItemTransaction.it_priceofcostpp` — `backend/app/models/item_transaction.py:33` (Numeric 18,4),
mapped 1:1 from the ERP field `it_priceOfCostPP` in
`backend/app/scripts/sync_item_transactions_incremental.py:148`.

"PP" = *precio ponderado*: this is the ERP's own weighted-average cost, and it is **already
replicated** into `tb_item_transactions` by the existing incremental sync (5-minute cadence,
`scriptItemTransaction`, documented in `backend/RELEVAMIENTO_GBP_PARSER_COMPLETO.md`).

A backend-wide grep shows `it_priceofcostpp` is written by the sync and **read nowhere** in business
logic — dormant, already-synced data. **No new ERP integration or GBP parser work is required.**

A sibling field `it_pricebofcostpp` ("before" variant) also exists. Production data confirms
`it_priceofcostpp` is the current value and `it_pricebofcostpp` the previous one — see the row-selection
section below. Use `it_priceofcostpp` from the item's latest qualifying transaction row.

## Currency — RESOLVED with production data (2026-07-27)

**There is no currency column for the cost fields.** `curr_id` (`item_transaction.py:28`) sits in the
"quantities and basic prices" block next to `it_price`: it is the currency of the *transaction*, not
of the cost. The six `it_priceofcost*` fields have no currency of their own, and the sync maps them
without one (`sync_item_transactions_incremental.py:147-149`).

Production queries settled it: **`it_priceofcostpp` is stored in ARS (branch currency)** and must NOT
be converted. Evidence — ratio `ppp / costo_lista` grouped by the product's list-cost currency:

| list currency | items | avg ratio |
|---|---|---|
| ARS | 26 | 0.49 |
| USD | 2048 | 2092.6 (≈ an exchange rate) |

### Anomaly: 1.81% of rows carry the PPP in USD

37 items (1.81% of those with a USD list cost) have the PPP expressed in USD instead of ARS.
The discriminator is **perfectly clean** — zero rows in the cross cells:

| `it_exchangetobranchcurrency IS NULL` | PPP looks like USD | items | ratio min | ratio max |
|---|---|---|---|---|
| false | false | 2011 | 49.42 | 1165073.39 |
| true  | true  | 37   | 1.0304 | 1.2530 |

There is no grey zone and no arbitrary threshold: the lowest normal ratio is 49, the highest
anomalous one is 1.25.

These rows should be **excluded, not converted**. They all share `supp_id` NULL, `coslis_id` NULL,
`it_priceofcostlastpurchase = 0`, and a PPP that is merely the list cost plus 3-25% — i.e. a value
inherited from the price list for items that never entered through a real purchase, not a weighted
average. Converting them would produce a tidy, false number.

Treating an unconverted USD PPP as pesos yields a markup in the tens of thousands of percent with no
error raised — a silent failure of the same family as the list-8 gotcha.

## History

No PPP history table is needed. `tb_item_transactions` *is* the historical ledger.
Recommendation: snapshot semantics (latest value per item), no new history table, no migration for
history.

## Row selection rule (settled)

```sql
it_priceofcostpp > 0
AND it_cancelled = false
AND it_exchangetobranchcurrency IS NOT NULL   -- drops the 37 USD-denominated rows
AND rmah_id IS NULL
AND it_isrmasuppliercreditnote = false        -- drops return cost, not replacement cost
ORDER BY it_cd DESC LIMIT 1                   -- per item_id
```

- Stock adjustments need no explicit exclusion: 2338 such rows carry **zero** PPP values.
- RMA rows do carry a PPP (2773 rows) but average $39,687 against $74,764 for normal rows — a
  downward bias, since a return is not a replacement cost. Excluding them changes the PPP of
  97 items and leaves 5 items without any PPP.
- `it_priceofcostpp` is the current value; `it_pricebofcostpp` is the previous one
  (60,222 rows with `pp > bpp` against 15,936 the other way — cost drifts upward over time).

## Markup derivation — reuse `calcular_markup`, backend-side

Do **not** reuse `calcular_precio_producto()` (`pricing_calculator.py:521`): it runs a goalseek from
cost to **price** (`precio_por_markup_goalseek(costo=costo_ars, ...)`, line 563). Feeding it the PPP
would return a different selling price, which is precisely what this change must not do.

Do reuse `calcular_markup(limpio, costo_ppp)`. In `productos_listing.py` the `limpio` value is
**already computed** at each of the ~10 markup sites (965, 996, 1049, 1092, 1127, 1390, 2138, 2164,
2252, 2493, 2530). One extra line next to each one, no new formula, no extra goalseek, no measurable
cost. Since the PPP is already in ARS, it is passed through untouched — the per-site
`convertir_a_pesos(...)` calls apply to the list cost only.

A frontend-side derivation was considered and rejected:
`markup_ppp = (costo / costo_ppp) * (1 + markup) - 1` is algebraically correct, but the markup
reaching the frontend is already rounded to 2 decimals, and each backend site converts the cost with
its own exchange-rate gate — a single payload figure cannot reproduce that.

No changes to `ProductoPricing` stored columns and no new filters: PPP markups stay strictly
display-only, matching the "informational, do not change the working method" requirement.

## Touch points

- Backend: subquery/join against `tb_item_transactions` for the latest `it_priceofcostpp` per
  `item_id`, exposed as `costo_ppp` in `productos_listing.py`.
- Frontend: one companion line under the cost cell (~1715) plus 10-12 companion lines under each
  markup spot; a shared `calcularMarkupPpp` helper belongs in `useProductosOffsets.js` next to
  `calcularMarkupConOffset`.

## Sync path

`tb_item_transactions` already syncs every 5 minutes — no new cron is required if the value is read
through a live join. Denormalizing `costo_ppp` onto `ProductoERP` is a performance/complexity
tradeoff to settle in the proposal.

## Coverage

Only **50%** of products can show a PPP: 2075 of 4147 rows in `productos_erp` have a qualifying
transaction. Age of the most recent PPP per item:

| age | items |
|---|---|
| 0-30 days | 461 |
| 31-90 days | 355 |
| 91-365 days | 837 |
| over 1 year | 430 |

Products without a PPP must render **"no data"** — never a silent fallback to the list cost.
Given that 430 items carry a PPP older than a year, showing the source date alongside the figure is
worth considering.

## Open questions

1. Denormalize `costo_ppp` onto `ProductoERP` (refreshed by the existing sync), or live-join per
   request? Performance/complexity tradeoff for the proposal.
2. Should the PPP source date be surfaced in the UI, given 430 items with a PPP older than a year?

## Risks

- **Silent currency failure** (mitigated): the 37 USD-denominated rows would render markups in the
  tens of thousands of percent without raising an error. Mitigated by the
  `it_exchangetobranchcurrency IS NOT NULL` filter, which separates the classes perfectly.
- 12+ edit locations in a 3111-line, CRLF-sensitive file, plus ~10 backend sites across three blocks
  that repeat the same pattern — must be sliced across PRs
  (suggested slices: 1. backend `costo_ppp` + PPP markups; 2. cost line + clasica/pvp;
  3. remaining variants).
- Half the catalogue has no PPP; the "no data" state is a first-class case, not an edge case.
- A stale PPP (over a year old) is informative but potentially misleading without its date.

## Status

Ready for proposal. Source, currency, row-selection rule, field semantics, derivation approach and
coverage are all settled against production data. The two remaining questions are design tradeoffs,
not blockers.

---

## SOURCE CORRECTION (2026-07-29) — everything above this line described the WRONG field

Post-ship verification against the live GBP ERP screen (the "Costo PPP" column) proved that
**`ItemTransaction.it_priceofcostpp` is NOT the ERP's weighted-average cost**. The correct source is
`ItemCostListHistory.iclh_price_aw` (`backend/app/models/item_cost_list_history.py:26`, whose own model
comment already read "Costo promedio ponderado" — this file never checked it).

Evidence, item 1169 (ROUTER TP LINK OMADA ER605), USD list cost 42.99, TC venta 1520:

| field | value | matches GBP screen (38.00)? |
|---|---|---|
| GBP "Costo PPP" column | 38.00 | — |
| `iclh_price_aw` (`coslis_id=1`, `curr_id=2`/USD, 2026-07-23) | 38.402760 | yes |
| `it_priceofcostpp` (shipped) | 71680.46 ARS / 1520 = 47.16 | no (~24% inflated) |

Across 2108 comparable products: `iclh_price_aw` matches `it_pricebofcostpp` (the "before" field, NOT
the one this document recommended) within 2% in 603 cases, but matches the field actually shipped
(`it_priceofcostpp`) in only 83.

### What went wrong

The identification above was based on:
1. The field NAME being plausible ("PP" = *precio ponderado*).
2. Internal consistency: the sync existed, the field was dormant/unread, and the `pp > bpp` drift
   statistic (§ "Row selection rule") was self-consistent with "current vs previous cost".

**It was never checked against a live ERP screen value** — the one check that would have caught the
mismatch immediately, before any code shipped. Order-of-magnitude plausibility and internal statistical
consistency are necessary but not sufficient: a wrong field can still look internally coherent if the
underlying ERP computation (list-cost-based cost-of-goods vs true weighted-average purchase cost) is
merely a *different*, equally well-behaved number.

### Corrected facts

- **Source**: `ItemCostListHistory.iclh_price_aw`, filtered to `coslis_id = 1` (the main cost list —
  the one whose `coslis_price` equals `productos_erp.costo`), `iclh_price_aw IS NOT NULL AND
  iclh_price_aw > 0`, latest `iclh_cd` wins, tiebreak on `iclh_id DESC` (the real, unique,
  monotonically-increasing surrogate key — mirrors the `it_transaction DESC` tiebreak this document's
  row-selection rule used for the old table).
- **Currency**: `iclh_price_aw` is in the cost list's OWN currency (`curr_id`; ERP convention 1=ARS,
  2=USD), the SAME currency as `producto_erp.costo`. It is **never converted for display** — a
  historical weighted average built from purchases at many different historical exchange rates cannot
  be reconstructed by dividing by today's rate (the previous implementation's ARS→USD-via-today's-rate
  "display" conversion, added in a later fix round, was itself a second, conceptually invalid bug).
  Conversion to ARS IS still needed, but only as an internal input to the markup formula
  (`calcular_markup(limpio, costo_ppp_ars)`, since `limpio` is always ARS) — never leaked back into the
  displayed figure.
- **Coverage**: ~77.5% of products (3215/4150) now qualify, up from the ~50% this document reported for
  the old field.
- **Sync**: `tb_item_cost_list_history` is synced by `sync_item_cost_history.n_incremental` every 5
  minutes (`backend/RELEVAMIENTO_GBP_PARSER_COMPLETO.md`: "tbItemCostListHistory | n_incremental | 5 min
  | ✅"), the same cadence this document already relied on for `tb_item_transactions` — no staleness
  regression.
- **Row-selection rule, currency anomaly analysis, and "denormalize vs live-join" tradeoff above this
  line are HISTORICAL and describe the wrong field.** They are left in place (not deleted) as the
  record of what was investigated and why it was wrong, not as current guidance.

## SCALE SANITY GUARD (2026-07-29) — THIRD data-trust failure in this feature

After the source correction above (wrong field) and a since-reverted fictitious cross-currency layer,
production surfaced a THIRD class of ERP data corruption: for a minority of products, `iclh_price_aw`
is left STALE at a different currency scale than `iclh_price` in the SAME row, after the product's cost
list moved between currencies.

**Witness — item 2780 (RESMA AUTOR CARTA)**, reported by a user who saw "2.91" displayed next to a
current cost of 3178.25:

| date | coslis_id | iclh_price | iclh_price_aw | curr_id |
|---|---|---|---|---|
| 2025-03-26 | 1 | 2.911820 | 2.911820 | 2 (USD) |
| 2025-07-28 | 1 | 3178.250000 | 2.911820 | 1 (ARS) |

The product moved from USD to ARS: `iclh_price`/`curr_id` were updated by the ERP; `iclh_price_aw` was
NOT recalculated and stayed at the old USD-scale figure. Ratio `iclh_price / iclh_price_aw` = 1091 — an
exchange rate of that period, not a costing difference. **This is NOT a currency-label divergence**:
`curr_id` (1 = ARS) matches `producto_erp.moneda_costo` (ARS) exactly — the existing currency-matching
verification (see "Currency — RESOLVED with production data" above and the module docstring in
`costo_ppp_service.py`) could never have caught this, because the broken value is the NUMBER itself,
not its currency label.

**Measurement (production, 2026-07-29)**, ratio `iclh_price / iclh_price_aw` on the row the resolver
picks for each of the 3215 products with a PPP:

| band | count | disposition |
|---|---|---|
| normal (0.5–2.0) | 3137 | kept |
| suspicious (2x–20x) | 50 | kept — plausibly a real cost swing |
| BROKEN, aw ~1000x too small | 23 (ratio 27.5 up to 53,249,815) | rejected |
| BROKEN, aw ~1000x too large | 20 (ratio 0.001–0.040) | rejected |

Cross-checked against `producto_erp.costo` instead of `iclh_price`: same 42 broken rows, 3172 coherent —
confirming the guard does not need to join out to `producto_erp`; validating `iclh_price_aw` against
`iclh_price` in the SAME row is sufficient and simpler.

**Fix**: `resolver_ppp_batch` now rejects a row when `iclh_price` is missing/`<= 0`, or when
`iclh_price / iclh_price_aw` falls outside `[0.05, 20]` (inclusive). A rejected row means the item has
NO PPP — there is no fallback to an older row (an older row is less trustworthy, not more, and the
resolver only ever considers the single latest qualifying row per item_id anyway). Net effect: coverage
drops from ~77.5% (3215/4150) to ~76.5% (3173/4150), discarding the 42 broken rows above.

**The pattern across all three failures in this feature**: an ERP value can never be trusted on its
own — it must be validated against a reference in the SAME row (first the field itself against a live
ERP screen value; now `iclh_price_aw` against `iclh_price`). "Looks like a plausible number, internally
consistent with the rest of the dataset" is necessary but not sufficient evidence of correctness.
