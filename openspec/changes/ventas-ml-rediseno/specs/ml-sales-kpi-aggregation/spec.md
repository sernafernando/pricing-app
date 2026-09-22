# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-sales-kpi-aggregation

### Requirements
- R7 A shared filter builder is used identically by the listing endpoint, the search, and the KPI aggregation endpoint — no divergent filter logic between them.
- R8 The KPI strip aggregates the FULL filtered set (not just the current page): count of orders, gross billed, neto ML, SUM of stored `total_gauss`, average markup.
- R9 Four doubtful-case toggle switches exist: "A revisar" (status unknown on operation or goods), "Mixta" (pack status mixed), "En disputa" (in_dispute), "Provisorio" (Total Gauss status provisional). Each is an independent on/off switch.
- R10 Each toggle, when OFF, excludes matching orders from BOTH the table listing and the KPI aggregation — table and KPI strip always reflect the exact same filtered set (per Q1).
- R11 Default toggle states on first load / no URL params: "A revisar" OFF, "En disputa" OFF, "Mixta" ON, "Provisorio" ON (per Q2).
- R12 Toggle state is persisted in URL query params, consistent with other filters on the screen (per Q3), so a shared/reloaded URL reproduces the same view.
- R13 The KPI strip reports how many orders were excluded by each currently-OFF toggle, so the user can see what is not being counted.
- R14 KPI results for a given filter+toggle combination equal the sum/aggregate of exactly the rows the listing would show for that same combination, EXCLUDING rows in the `recalculating` or `pending` state (parity, no drift). Those excluded rows are still listed (with their badge) and are reconciled through `recalculating_count` and `pending_count`: listed rows = rows summed + recalculating_count + pending_count.
- R15 The KPI/filter contract (shared filter builder, stored per-order metrics, toggle semantics) must be reusable by future metric consumers (e.g. a future sell-in/sell-out per-product-promotion metrics feature) — it must not be hardwired to only this screen's response shape.

### Scenarios
1. Given default toggle states (A revisar OFF, En disputa OFF, Mixta ON, Provisorio ON) and no URL params, when the screen loads, then the table shows only orders passing those defaults and the KPI strip sums exactly those same orders.
2. Given the user turns "Mixta" OFF, when the KPI strip and table re-render, then orders whose pack status is `mixed` disappear from both the table rows and the KPI sums simultaneously, and the KPI strip shows the count of excluded mixed orders.
3. Given a pack contains a mix of resolved and provisional sub-orders, when "Provisorio" is OFF, then the entire pack-affecting rule is applied consistently (defined at the pack level, not silently per sub-row) — pack-level inclusion/exclusion must not produce a table row that contradicts what the KPI counted for that pack.
4. Given the user sets toggles to a specific combination and copies the URL, when another user (or the same user in a new tab) opens that URL, then the same toggle states and results are reproduced.
5. Given "A revisar" is turned ON, when the KPI strip recalculates, then orders with unknown operation or goods status are included in both the sum and the table, and the previously-shown excluded count for that toggle disappears/updates.
6. Given a filtered set combining date range, status facets, search text, and toggle states, when the KPI aggregation runs, then it reflects the intersection of ALL active filters — not toggles alone.
7. Given two consumers (this screen's KPI and, in a future change, a different metrics screen) apply the same filter+toggle parameters, when both call the shared filter/aggregation contract, then they receive consistent results, proving the contract is not hardwired to one screen.
