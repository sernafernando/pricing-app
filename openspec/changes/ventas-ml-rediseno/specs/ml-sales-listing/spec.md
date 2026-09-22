# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-sales-listing (modified)

### Requirements
- R28 The listing response is additive: existing fields keep their name/shape; new optional fields are added (thumbnail placeholder, city/province, shipment substatus, ML coupon amount, buyer real name if present, unified alert level).
- R29 A unified alert level (ok/warning/error) is derived server-side from existing status/provisional/incomplete signals, replacing ad-hoc per-field flags in the UI.
- R30 Facet chips display live counts consistent with the currently active filter set (including toggles and search).
- R31 Listing values for neto/Total Gauss/markup come from the stored metrics record (ml-order-stored-metrics), not a live recompute.

### Scenarios
1. Given an order with no persisted city data, when the listing renders, then the city field is omitted/blank rather than showing invented data.
2. Given an order's operation_status is `unknown` and goods_status is resolved, when the alert level is derived, then it reflects at least a "warning"/"needs review" level server-side, consistent with what the "A revisar" toggle targets.
3. Given the facets are computed for the current filter+search+toggle combination, when the listing renders chip counts, then those counts match the actual number of rows a user would get by clicking that chip (no drift between displayed count and result count).
4. Given the stored metrics record for an order is `unresolved`, when the listing renders its Total Gauss column, then it shows an explicit unresolved indicator, not blank-as-zero or a stale number.
