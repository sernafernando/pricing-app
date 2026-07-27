# Proposal: Informational PPP cost and PPP markups in Productos

## Intent

The Productos list prices and reports margin against the **cost list** price. That is the working
method and it stays. But the real earned margin is against the ERP weighted-average cost
(`it_priceofcostpp`, "precio ponderado"), which is already synced every 5 minutes and read nowhere.
Buyers cannot see what a product actually earns against what it actually cost. This change surfaces
that number **for information only**.

## Scope

### In Scope
- Backend exposes `costo_ppp` (ARS) + `costo_ppp_fecha` (`it_cd` of the source row) in `productos_listing.py`.
- Backend computes display-only PPP markups via `calcular_markup(limpio, costo_ppp)` at the ~10 existing sites.
- Frontend: a companion line under the cost cell and under each of the 12 markup render spots.
- Explicit "no data" state (~50% of the catalogue) and unconditional source-date display.

### Out of Scope
- Any change to selling prices, `calcular_precio_producto()`, goalseek, or stored pricing columns.
- New SQL filters, sort keys, or `ProductoPricing` columns — PPP is never persisted or filterable.
- Currency conversion of the PPP; USD-denominated rows are excluded, not converted.
- A PPP history table or new cron/ERP integration.

## Capabilities

### New Capabilities
- `productos-costo-ppp`: informational weighted-average cost and its derived markups in the product list.

### Modified Capabilities
- None (no existing spec-level requirement changes; pricing behaviour is untouched).

## Approach

**Row selection** (settled in exploration), per `item_id`:
`it_priceofcostpp > 0 AND it_cancelled = false AND it_exchangetobranchcurrency IS NOT NULL
AND rmah_id IS NULL AND it_isrmasuppliercreditnote = false ORDER BY it_cd DESC LIMIT 1`.

**Read strategy**: a live `DISTINCT ON`/`LATERAL` join against `tb_item_transactions` — **not**
denormalization onto `productos_erp`. The table already refreshes every 5 minutes; denormalizing
would add a migration plus a refresh job to keep fresh something that already is. Revisit only if
the listing endpoint measurably degrades.

**Performance**: `productos_listing.py` is a hot endpoint. The join MUST be a single set-based
LATERAL over the page's item ids — no per-row query (N+1 is the main failure mode here). The model
indexes `item_id` and `it_cd` **separately**; a composite `(item_id, it_cd DESC)` index is likely
required for the LIMIT 1 per item to stay cheap. Measure before and after; add the index in the
backend slice if EXPLAIN shows a sort.

**Derivation**: reuse `calcular_markup(limpio, costo_ppp)` where `limpio` already exists (lines 965,
996, 1049, 1092, 1127, 1390, 2138, 2164, 2252, 2493, 2530). PPP is already ARS — no
`convertir_a_pesos` call applies to it. No new formula.

**UI shape**: under the cost cell (`Productos.jsx:1715`) a muted `PPP $X · dd/mm/yyyy` line; under
each markup (1765, 1772, 1933, 2044, 2096, 2129, 2162, 2195, 2235, 2270, 2305, 2340) a muted
`ppp: n%`. A shared `calcularMarkupPpp`-style formatter lives with `useProductosOffsets.js`.

## Contracts

- **No-data contract**: if no qualifying row exists, backend returns `costo_ppp = null` and the UI
  renders an explicit "sin PPP" marker. It MUST NEVER fall back to `costo`. A wrong informational
  number drives real purchasing decisions.
- **Date contract**: the source date is shown **always**, next to every PPP figure, regardless of
  age. No staleness threshold, no age-conditional styling. One rule, not two — 430 items carry a
  PPP older than a year and a stale PPP silently overstates profitability.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/api/endpoints/productos_listing.py` | Modified | LATERAL join, `costo_ppp`/`costo_ppp_fecha`, ~10 markup sites |
| `backend/app/models/item_transaction.py` | Modified (maybe) | composite `(item_id, it_cd DESC)` index if EXPLAIN requires |
| `frontend/src/pages/Productos.jsx` | Modified | cost line + 12 markup companion lines |
| `frontend/src/hooks/useProductosOffsets.js` | Modified | shared PPP formatter |

## Delivery Plan (400-line review budget)

`Productos.jsx` is 3111 lines and historically CRLF-troubled (now forced to LF by `.gitattributes`);
if renormalization noise appears, isolate it in its own commit before the feature commit.

1. **PR1 — backend**: join, `costo_ppp` + `costo_ppp_fecha`, PPP markups, index, tests. Self-contained; frontend ignores unknown fields.
2. **PR2 — frontend base**: cost-cell PPP line + no-data + date rendering + shared formatter + first markup group (clasica 1765/1772).
3. **PR3 — remaining markup variants**: mejor oferta, web_real, 3/6/9/12 cuotas, pvp cuotas.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Silent currency failure (USD-denominated PPP → markup in the tens of thousands of %) | Med | `it_exchangetobranchcurrency IS NOT NULL` filter; classes separate perfectly (max anomalous ratio 1.25 vs min normal 49) |
| Listing endpoint slowdown / N+1 | Med | Single set-based LATERAL scoped to the page; composite index; EXPLAIN before/after |
| Stale PPP read as current | Med | Source date shown unconditionally |
| Fallback to list cost sneaks in during 12 edit sites | Med | Explicit no-data contract + review; null must render as marker |
| CRLF/whitespace noise swamping review | Med | Renormalization isolated in its own commit; 3-PR slicing |

## Rollback Plan

Display-only and additive: no migration (beyond an optional index), no stored columns, no pricing
change. Revert the PR(s); the frontend tolerates a missing `costo_ppp` field and the backend
tolerates the UI not reading it. The optional index can be dropped independently.

## Dependencies

- Existing 5-minute `sync_item_transactions_incremental.py` cadence (already running).

## Success Criteria

- [ ] PPP and its source date visible for the ~2075 products with a qualifying row.
- [ ] Products without a qualifying row show an explicit no-data marker, never a list-cost fallback.
- [ ] Zero change to selling prices, stored markups, filters, and sorting (regression-verified).
- [ ] No USD-denominated PPP reaches the UI.
- [ ] Listing endpoint p95 latency unchanged within noise.

## Proposal question round

No blocking questions. All three former assumptions are now resolved:
1. **RESOLVED (production data).** `it_priceofcostpp` is the current value, `it_pricebofcostpp` the
   previous one: 60,222 rows have `pp > bpp` against 15,936 the other way, consistent with cost
   drifting upward over time. Not an assumption — measured.
2. **RESOLVED (user decision).** PPP markups render for **all 12** markup variants, not only the
   primary ones. Rationale: where there is a markup, there is a ppp — no gaps.
3. **RESOLVED (user decision).** Date format is `dd/mm/aa`, always shown, never relative wording.
   A relative label ("hace 8 meses") forces mental arithmetic on every read and ages badly in a
   cached render.
