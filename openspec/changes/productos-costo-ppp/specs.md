# Spec: productos-costo-ppp

## Purpose

Surface the ERP weighted-average cost (`it_priceofcostpp`, "PPP") and PPP-derived markups
in the Productos list as **informational, display-only** data. The list-cost pricing method,
stored markups, filters, and selling prices are unchanged.

## Requirements

### Requirement: PPP row selection per item

The system MUST select at most one `tb_item_transactions` row per `item_id` as the PPP source,
using: `it_priceofcostpp > 0 AND it_cancelled = false AND it_exchangetobranchcurrency IS NOT NULL
AND rmah_id IS NULL AND it_isrmasuppliercreditnote = false`, ordered by `it_cd DESC`, `LIMIT 1`.

#### Scenario: Item has one qualifying row

- GIVEN an item with a single `tb_item_transactions` row satisfying all five predicates
- WHEN the Productos listing endpoint computes `costo_ppp` for that item
- THEN the endpoint uses that row's `it_priceofcostpp` as `costo_ppp`

#### Scenario: Item has multiple qualifying rows

- GIVEN an item with several qualifying rows at different `it_cd` values
- WHEN the endpoint computes `costo_ppp`
- THEN it selects only the row with the highest `it_cd` (most recent)

#### Scenario: USD-denominated PPP is excluded, never converted

- GIVEN an item whose only PPP-eligible row has `it_exchangetobranchcurrency IS NULL`
  (PPP expressed in USD, not ARS)
- WHEN the endpoint computes `costo_ppp`
- THEN that row MUST NOT be selected and MUST NOT be currency-converted
- AND the item is treated as having no qualifying row for PPP purposes

#### Scenario: RMA and cancelled rows are excluded

- GIVEN an item whose only rows are cancelled, RMA-linked (`rmah_id` not null),
  or RMA supplier credit notes
- WHEN the endpoint computes `costo_ppp`
- THEN none of those rows are selected

### Requirement: PPP is already in ARS — no currency conversion

The system MUST pass the selected `it_priceofcostpp` value directly to
`calcular_markup(limpio, costo_ppp)` with no `convertir_a_pesos` or other currency conversion step,
even though the list-cost path at the same call site converts `costo` per the item's site/currency.

#### Scenario: PPP markup computed alongside list-cost markup

- GIVEN a markup site in `productos_listing.py` where `limpio` is already computed and the list
  cost `costo` is converted via `convertir_a_pesos(costo, ...)` before `calcular_markup(limpio, costo)`
- WHEN the same site also computes the PPP markup
- THEN it calls `calcular_markup(limpio, costo_ppp)` using the raw (unconverted) `costo_ppp` value

### Requirement: PPP source date always displayed

The system MUST return the source row's `it_cd` as `costo_ppp_fecha` whenever `costo_ppp` is
non-null, and the frontend MUST render this date next to every PPP figure, unconditionally,
regardless of its age, formatted as `dd/mm/aa`. No staleness threshold, badge, color change, or
relative wording ("hace X meses") is permitted.

#### Scenario: Recently sourced PPP shows its date

- GIVEN an item whose selected PPP row has `it_cd` from 10 days ago
- WHEN the PPP line renders in the UI
- THEN it shows the PPP value and `dd/mm/aa` of that date, with no special styling

#### Scenario: Old PPP shows its date the same way

- GIVEN an item whose selected PPP row has `it_cd` more than one year old
- WHEN the PPP line renders in the UI
- THEN it shows the PPP value and its `dd/mm/aa` date with the exact same styling as a recent one
- AND no staleness warning, badge, or relative-age text is rendered

### Requirement: Explicit no-data state, never a cost fallback

The system MUST render an explicit "no PPP data" marker for any product with no qualifying
`tb_item_transactions` row. It MUST NEVER substitute the list cost (`costo`) or any derived value
as a stand-in for a missing PPP, in either the backend payload or the frontend rendering.

#### Scenario: Product with no qualifying row

- GIVEN a product with zero rows satisfying the PPP row-selection predicate
- WHEN the Productos listing endpoint serializes that product
- THEN `costo_ppp` and `costo_ppp_fecha` are both `null`
- AND the frontend renders an explicit "sin PPP" (or equivalent) marker in place of a value
- AND no PPP markup line is rendered under that product's markup cells

#### Scenario: No-data state never falls back to list cost

- GIVEN a product with `costo_ppp = null`
- WHEN the frontend renders the PPP line under the cost cell and every markup spot
- THEN none of those lines display `costo` or any markup computed from `costo` as if it were PPP

### Requirement: PPP markups render at all display sites

The system MUST render a PPP-derived cost line under the cost cell (Productos.jsx line 1715) and a
PPP-derived markup line under each of the following 12 existing markup render spots: 1765, 1772,
1933, 2044, 2096, 2129, 2162, 2195, 2235, 2270, 2305, 2340.

#### Scenario: All 12 markup spots show a companion PPP line

- GIVEN a product with a non-null `costo_ppp`
- WHEN the product row renders in Productos.jsx
- THEN each of the 12 markup spots shows its existing list-cost markup plus a PPP markup line
  computed via `calcular_markup(limpio, costo_ppp)` at the corresponding backend site

#### Scenario: Cost cell shows the PPP cost line

- GIVEN a product with a non-null `costo_ppp`
- WHEN the cost cell (line 1715) renders
- THEN a companion line below it shows the PPP value and its source date

### Requirement: No change to selling prices, stored markups, or filters

The system MUST NOT alter `calcular_precio_producto()`, any stored `ProductoPricing` column
(`markup_calculado`, `markup_rebate`, `markup_oferta`, `markup_web_real`), any SQL list filter, or
any sort key as a result of introducing PPP. PPP values and PPP markups are computed for display
only and are never persisted or filterable.

#### Scenario: Existing prices and markups are byte-identical

- GIVEN the Productos listing endpoint response for a fixed set of products before this change
- WHEN the same request is made after this change ships
- THEN every existing field (`precio`, `costo`, `markup_calculado`, `markup_rebate`,
  `markup_oferta`, `markup_web_real`, and all other pre-existing fields) is byte-identical
- AND the only difference is the addition of `costo_ppp`, `costo_ppp_fecha`, and PPP markup fields

#### Scenario: Filtering and sorting behavior unchanged

- GIVEN an existing list filter or sort order based on stored markup/price columns
- WHEN the same filter or sort is applied after this change
- THEN the result set and order are identical to before the change
