# ml-ventas-total-gauss Specification

## Purpose

"% de varios" deduction base for Total Gauss: computed per-item from gross unit price and each item's own IVA rate, sourced from the frozen cost snapshot, with missing-input handling and the live-vs-stored value distinction.

Source: archived change openspec/changes/archive/2026-09-22-ml-ventas-neto-iibb-varios/

## Requirements

### Requirement: "% de varios" deduction base

The system MUST compute the base for the "% de varios" (`VariosDeduccion`) percentage deduction as the sum, across all order items, of each item's gross unit price times quantity divided by (1 + that item's own IVA rate) — i.e., the operation amount WITHOUT IVA, using each item's own rate for mixed-rate packs — sourced from the same frozen `MlOrderItemCosto.precio_unitario` / `iva_pct` snapshot used to build the IVA split's "Venta" components. The resulting percentage amount MUST be subtracted from `neto_sin_iva` at the end of the Total Gauss deduction chain, after all other deductions.

#### Scenario: Worked example varios calculation

- GIVEN order 2000018567320906 with total item gross (with IVA) of 597408.67 and a uniform 21% IVA rate on all items, and a 5% "varios" rate configured
- WHEN the system computes the varios base
- THEN the base equals 597408.67 / 1.21 = 493726.17
- AND the varios deduction equals 493726.17 × 5% = 24686.31
- AND this amount is subtracted from `neto_sin_iva` at the end of the Total Gauss chain

#### Scenario: Mixed-rate pack

- GIVEN an order with multiple items where at least two items have different IVA rates (e.g. 21% and 10.5%)
- WHEN the system computes the varios base
- THEN each item's gross amount is divided by (1 + that item's own IVA rate) before summing, so no item uses another item's rate

#### Scenario: Missing frozen cost snapshot for an item

- GIVEN an order item with no corresponding `MlOrderItemCosto` row (frozen cost snapshot missing)
- WHEN the system computes the varios base for that order
- THEN the varios amount for that order MUST be treated as unresolved/unknown, consistent with how the rest of the Total Gauss chain treats missing frozen-cost inputs (it MUST NOT silently default to 0 unless that is the documented existing behavior for other missing-input cases in the chain)
- AND the order's Total Gauss / varios result surfaces this unresolved state the same way existing missing-cost-snapshot cases do elsewhere in the chain

#### Scenario: Displayed values use current rules; stored values are backfilled separately

- GIVEN a user views the Total Gauss / Neto / IVA breakdown for any order (new or existing) through the live drawer/API
- WHEN the system computes the displayed values
- THEN they are computed live using the SIRTAC add-back, withdrawal-tax, and varios-base rules above, regardless of the stored `total_gauss` column's value
- AND the stored `total_gauss` column is not recomputed by this computation path; it is kept current by the separate `ml-order-stored-metrics` capability (change `ventas-ml-rediseno`), whose worker recomputes every stored value on a `formula_version` bump
