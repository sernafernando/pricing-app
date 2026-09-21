# Delta Spec: ML Sales Net — SIRTAC Add-Back, Withdrawal Tax, Varios Base (engram mode, concatenated, no openspec/ dirs written)

## Domain: ml-ventas-iva-breakdown

### MODIFIED Requirements

### Requirement: IVA component reconciliation
The system MUST decompose an order's charges into IVA components (`ComponenteIVA` list) such that, for orders without the new débitos/créditos extra component, the sum of component gross amounts (`suma_bruto`) equals Neto (`reconcilia == True`). The SIRTAC withholding charge MUST be represented as an informational component that displays its amount but contributes 0 to `suma_bruto` / `neto_sin_iva`. The system MUST add a new, IVA-free component labeled "Impuesto a los débitos y créditos (retiro)" equal to the non-refunded amount of the `collector-debitos_creditos` charge on any order carrying that charge, independent of whether SIRTAC is present on the order. This extra component MUST lower `neto_sin_iva` (and therefore Total Gauss) but MUST NOT change displayed Neto. The reconciliation invariant becomes: `sum(componentes.bruto) == neto − extra_debitos_creditos` (where `extra_debitos_creditos` is 0 when no débitos/créditos charge exists on the order).
(Previously: SIRTAC contributed `-net_amount(charge)` to `suma_bruto` like every other tax-type charge; reconciliation required `sum(componentes.bruto) == neto` with no extra term; there was no débitos/créditos doubling.)

#### Scenario: Worked example reconciles with the extra term
- GIVEN order 2000018567320906 as in the Neto scenario above (Neto 503958.14, SIRTAC 1792.23, débitos/créditos 3584.45)
- WHEN the system builds the IVA component breakdown
- THEN the SIRTAC component displays 1792.23 but contributes 0 to `suma_bruto`
- AND a new component "Impuesto a los débitos y créditos (retiro)" of 3584.45 is present and lowers `neto_sin_iva` by 3584.45
- AND `reconcilia == True` with `sum(componentes.bruto) == 503958.14 − 3584.45`

#### Scenario: Order with no débitos/créditos charge
- GIVEN an order that has no `collector-debitos_creditos` charge
- WHEN the system builds the IVA component breakdown
- THEN no extra "Impuesto a los débitos y créditos (retiro)" component is added
- AND the reconciliation invariant reduces to `sum(componentes.bruto) == neto`

#### Scenario: Débitos/créditos extra applies without SIRTAC present
- GIVEN an order with a non-refunded `collector-debitos_creditos` charge but no SIRTAC withholding charge
- WHEN the system builds the IVA component breakdown
- THEN the extra "Impuesto a los débitos y créditos (retiro)" component is still added, lowering `neto_sin_iva` by the non-refunded charge amount

#### Scenario: Débitos/créditos partially refunded
- GIVEN an order whose débitos/créditos charge has a nonzero refunded portion
- WHEN the system builds the extra component
- THEN the extra component amount equals only the non-refunded portion of the charge

#### Scenario: Normal order (no SIRTAC, no débitos/créditos) still reconciles
- GIVEN an order with only ordinary sale, fee, and shipping charges (no SIRTAC, no débitos/créditos, no Retención)
- WHEN the system builds the IVA component breakdown
- THEN `reconcilia == True` and `sum(componentes.bruto) == neto` exactly, unaffected by this change
