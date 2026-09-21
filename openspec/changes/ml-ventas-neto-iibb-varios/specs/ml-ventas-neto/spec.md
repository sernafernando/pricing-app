# Delta Spec: ML Sales Net — SIRTAC Add-Back, Withdrawal Tax, Varios Base (engram mode, concatenated, no openspec/ dirs written)

## Domain: ml-ventas-neto

### MODIFIED Requirements

### Requirement: Displayed Neto computation
The system MUST compute the displayed Neto for an ML order as the seller's effective net received amount PLUS the non-refunded amount of any IIBB SIRTAC withholding charge (`tax_withholding_sirtac-<prov>`) on that order. The `sirtac_sobretasa` charge, `collector-debitos_creditos` (débitos y créditos) charge, and any withholding charge classified as a generic "Retención" (no matched regime) MUST continue to be subtracted from Neto exactly as before this change. `compute_breakdown` and `compute_neto_by_order_ids` MUST apply this rule identically and MUST always agree on Neto for the same order.
(Previously: Neto subtracted the non-refunded SIRTAC amount like every other withholding charge, with no informational add-back.)

#### Scenario: Order with SIRTAC, débitos/créditos, and no refunds (worked example)
- GIVEN order 2000018567320906 with `monto_operacion` 597408.67, ML fee 74676.08, `shp_cross_docking` 15190, SIRTAC (CABA) withholding 1792.23 (fully non-refunded), débitos y créditos charge 3584.45 (fully non-refunded), and ML `net_received_amount` 502165.91
- WHEN the system computes Neto for this order
- THEN Neto equals 503958.14 (502165.91 + 1792.23)
- AND the SIRTAC amount 1792.23 is exposed as an informational line, not subtracted from Neto

#### Scenario: SIRTAC partially refunded
- GIVEN an order whose SIRTAC withholding charge has amount A and a nonzero `refunded` amount R (0 < R < A)
- WHEN the system computes Neto
- THEN only the non-refunded portion (A − R) is added back to Neto

#### Scenario: SIRTAC fully refunded
- GIVEN an order whose SIRTAC withholding charge is fully refunded (refunded == amount)
- WHEN the system computes Neto
- THEN the add-back is 0 and Neto equals the seller's effective net received amount unmodified by SIRTAC

#### Scenario: Order with only sobretasa (no SIRTAC withholding)
- GIVEN an order that has a `sirtac_sobretasa` charge but no `tax_withholding_sirtac-<prov>` withholding charge
- WHEN the system computes Neto
- THEN the sobretasa amount is subtracted from Neto as before this change
- AND no SIRTAC add-back is applied

#### Scenario: Order with a generic Retención (unmatched regime)
- GIVEN an order with a withholding-type charge that does not match the SIRTAC classifier (no recognized provincial regime)
- WHEN the system computes Neto
- THEN the charge is subtracted from Neto as a generic Retención, unchanged from prior behavior

#### Scenario: The two net computation paths agree
- GIVEN any order with a mix of SIRTAC, sobretasa, débitos/créditos, and Retención charges (with and without refunds)
- WHEN Neto is computed via `compute_breakdown` and independently via `compute_neto_by_order_ids`
- THEN both paths return the same Neto value for that order
