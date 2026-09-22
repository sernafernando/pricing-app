# ml-ventas-desglose-ui Specification

## Purpose

Drawer display rules for the SIRTAC informational line, the débitos/créditos withdrawal-tax line, and the Neto sub-line explaining the SIRTAC add-back.

Source: archived change openspec/changes/archive/2026-09-22-ml-ventas-neto-iibb-varios/

## Requirements

### Requirement: Drawer display of SIRTAC, withdrawal tax, and Neto sub-line

The system MUST display the SIRTAC withholding amount as an informational line (not part of the subtracted-from-Neto list), using a distinct `origen` value from the existing "propio" mechanism used for Flex freight. The system MUST display the débitos/créditos withdrawal extra component as a labeled line "Impuesto a los débitos y créditos (retiro)". The system MUST display Neto with a sub-line reading "ML depositó $X · SIRTAC $Y se recupera a fin de mes", where X is the seller's effective net received amount and Y is the non-refunded SIRTAC amount.

#### Scenario: Drawer renders worked example

- GIVEN order 2000018567320906 as computed above (Neto 503958.14, ML deposited 502165.91, SIRTAC 1792.23, extra débitos/créditos 3584.45)
- WHEN the drawer renders the breakdown
- THEN Neto shows 503958.14 with sub-line "ML depositó $502165.91 · SIRTAC $1792.23 se recupera a fin de mes"
- AND the SIRTAC line is shown informationally and excluded from the set of lines the drawer subtracts against Neto (same filtering mechanism as `origen !== 'propio'`)
- AND the "Impuesto a los débitos y créditos (retiro)" line of 3584.45 is shown

## Non-Requirements (explicitly out of scope)

- `pricing_calculator.calcular_comision_ml_total` / `varios_porcentaje` (forward-pricing estimate) behavior is unaffected; only its cross-reference in `VariosDeduccion`'s docstring changed.
- No migration or script recomputes/backfills the stored `total_gauss` column as part of the `ml-ventas-neto-iibb-varios` change; the existing sweep (`refrescar_total_gauss_pendientes`) and the `ml-order-stored-metrics` capability (change `ventas-ml-rediseno`) are the recompute paths for the stored column.
- Treatment of `sirtac_sobretasa` and generic Retención withholdings is unchanged.

## Key Learnings

- **Reconciliation coupling is the central risk**: any change to Neto computation (`payment_effective_net`) must be mirrored by an exactly equal-and-opposite change to `descomponer_neto`'s component construction, or `reconcilia` flips to False in production. This spec encodes the new invariant explicitly (`sum(componentes.bruto) == neto − extra_debitos_creditos`) precisely so it is testable per-order, not just narratively described.
- **Two independent Neto code paths must be pinned to agree**: `compute_breakdown` and `compute_neto_by_order_ids` are separate call sites over the same underlying logic; a scenario explicitly requires their agreement (mirrors existing `TestTheTwoPathsToTheNetAgree`).
- **Débitos/créditos extra is unconditional**: it applies to every order with a non-refunded débitos/créditos charge, independent of whether SIRTAC exists on that order — captured as its own scenario to avoid the two rules being accidentally coupled in implementation.
- **Varios base source is pinned to the frozen `MlOrderItemCosto` snapshot** (same source as IVA "Venta" components), not `MlOrderItemOps`/`monto_operacion`.
- **Missing-frozen-cost handling for varios must not silently produce 0.** The scenario says "unresolved, consistent with existing missing-input handling" rather than inventing a new sentinel value, pinning the non-negotiable behavior (never silently 0) while leaving the exact mechanism to implementation.
- **Stored `total_gauss` backfill is a separate capability.** This change's live computation is correct immediately after deploy regardless of the stored column's value; the stored column is kept current by `ml-order-stored-metrics` (change `ventas-ml-rediseno`), not by this change.
- **All Given/When/Then scenarios reuse the exact worked-example figures** (order 2000018567320906: Neto 503958.14, ML deposited 502165.91, SIRTAC 1792.23, extra débitos 3584.45, varios base 493726.17, 5% = 24686.31), so tests derived from this spec can assert on real captured numbers rather than invented fixtures, consistent with the project's "fixtures captured, not invented" convention.
