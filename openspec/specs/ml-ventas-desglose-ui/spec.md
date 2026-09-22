# Delta Spec: ML Sales Net — SIRTAC Add-Back, Withdrawal Tax, Varios Base (engram mode, concatenated, no openspec/ dirs written)

## Domain: ml-ventas-desglose-ui

### MODIFIED Requirements

### Requirement: Drawer display of SIRTAC, withdrawal tax, and Neto sub-line
The system MUST display the SIRTAC withholding amount as an informational line (not part of the subtracted-from-Neto list), using a distinct `origen` value from the existing "propio" mechanism used for Flex freight. The system MUST display the débitos/créditos withdrawal extra component as a labeled line "Impuesto a los débitos y créditos (retiro)". The system MUST display Neto with a sub-line reading "ML depositó $X · SIRTAC $Y se recupera a fin de mes", where X is the seller's effective net received amount and Y is the non-refunded SIRTAC amount.
(Previously: SIRTAC rendered as a normal subtracted line with no informational marker; no withdrawal-tax line existed; no Neto sub-line existed.)

#### Scenario: Drawer renders worked example
- GIVEN order 2000018567320906 as computed above (Neto 503958.14, ML deposited 502165.91, SIRTAC 1792.23, extra débitos/créditos 3584.45)
- WHEN the drawer renders the breakdown
- THEN Neto shows 503958.14 with sub-line "ML depositó $502165.91 · SIRTAC $1792.23 se recupera a fin de mes"
- AND the SIRTAC line is shown informationally and excluded from the set of lines the drawer subtracts against Neto (same filtering mechanism as `origen !== 'propio'`)
- AND the "Impuesto a los débitos y créditos (retiro)" line of 3584.45 is shown

---

## Non-Requirements (explicitly out of scope, confirmed by proposal adjustments)

- `pricing_calculator.calcular_comision_ml_total` / `varios_porcentaje` (forward-pricing estimate) MUST NOT change behavior as part of this delta; only its cross-reference in `VariosDeduccion`'s docstring is updated.
- No migration or script recomputes/backfills the stored `total_gauss` column as part of this change (dropped from proposal scope per orchestrator adjustment); the existing sweep (`refrescar_total_gauss_pendientes`) and the paused `ventas-ml-rediseno` worker remain the only future recompute paths.
- Treatment of `sirtac_sobretasa` and generic Retención withholdings is unchanged.

## Key Learnings

- **Reconciliation coupling is the central risk**: any change to Neto computation (`payment_effective_net`) must be mirrored by an exactly equal-and-opposite change to `descomponer_neto`'s component construction, or `reconcilia` flips to False in production. This delta spec encodes the new invariant explicitly (`sum(componentes.bruto) == neto − extra_debitos_creditos`) precisely so it is testable per-order, not just narratively described.
- **Two independent Neto code paths must be pinned to agree**: `compute_breakdown` and `compute_neto_by_order_ids` are separate call sites over the same underlying logic; a scenario explicitly requires their agreement (mirrors existing `TestTheTwoPathsToTheNetAgree`).
- **Débitos/créditos extra is unconditional**: per orchestrator adjustment, it applies to every order with a non-refunded débitos/créditos charge, independent of whether SIRTAC exists on that order — this is captured as its own scenario to avoid the two rules being accidentally coupled in implementation.
- **Varios base source is pinned to the frozen `MlOrderItemCosto` snapshot** (same source as IVA "Venta" components), not `MlOrderItemOps`/`monto_operacion` — this was an open question in the proposal, resolved by the orchestrator's binding adjustment, and is now a normative part of the requirement text (not just an implementation note) since it changes which value the spec's worked-example scenario must reproduce.
- **Missing-frozen-cost handling for varios must not silently produce 0.** The proposal never verified what the existing Total Gauss chain currently does when a frozen cost snapshot is missing for other inputs; the scenario says "unresolved, consistent with existing missing-input handling" rather than inventing a new sentinel value, deferring the exact mechanism to design/implementation while pinning the non-negotiable behavior (never silently 0).
- **Stored `total_gauss` backfill (originally PR4) is explicitly out of scope** in this revision — the proposal's Alembic migration/stale-marking PR is dropped per orchestrator instruction; a scenario positively asserts that displayed values are correct live immediately after deploy regardless of the stored column, so this drop doesn't leave an implicit "everything is right except old cached values are wrong forever" gap unaddressed at the spec level.
- **All Given/When/Then scenarios reuse the exact worked-example figures** (order 2000018567320906: Neto 503958.14, ML deposited 502165.91, SIRTAC 1792.23, extra débitos 3584.45, varios base 493726.17, 5% = 24686.31) supplied by the orchestrator, so tests derived from this spec can assert on real captured numbers rather than invented fixtures, consistent with the project's "fixtures captured, not invented" convention.
