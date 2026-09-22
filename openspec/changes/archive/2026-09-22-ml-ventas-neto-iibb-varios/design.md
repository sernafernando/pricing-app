# Design: ML sales net — SIRTAC add-back, débitos/créditos withdrawal tax, Varios on goods without IVA

Binding adjustments applied: NO stale-marking migration, NO cron. Stored `total_gauss` is a sort key; displayed values are live (calcular_total_gauss is always recomputed). The paused `ventas-ml-rediseno` worker recomputes via formula_version. Débitos/créditos extra applies to EVERY order with a non-refunded collector charge. Varios base = Σ frozen MlOrderItemCosto precio_unitario*qty/(1+iva_pct/100), i.e. the SAME per-item bases as the IVA "Venta" components.

## Technical Approach
All three rules hang off ONE classifier in breakdown_service.py, reused by iva.py and compute_breakdown. The neto rule (R1) lives inside `payment_effective_net`, which all three net paths already share (compute_neto_by_order_ids:916, compute_breakdown:968, descomponer_neto iva.py:237), so the paths agree by construction. The IVA split (R2) computes the extra débitos amount once, in descomponer_neto, and changes the reconciliation target to `neto - extra`. Varios (R3) gets a new base identifier `"venta_sin_iva"` whose value is produced by descomponer_neto (already run by every total_gauss caller) and passed into calcular_total_gauss as a new required keyword map.

## Architecture Decisions

### D1 — Single withholding classifier (breakdown_service.py)
**Choice**: add `withholding_kind(charge_name: Optional[str]) -> Optional[str]` next to `tax_label` (breakdown_service.py:303). It performs the exact parsing `tax_label` already does (`_TAX_PREFIX`, `kind_slug.lstrip("_")`, `place_slug` required) and returns the `_TAX_KINDS` key: `"sirtac"`, `"sirtac_sobretasa"`, `"collector"`, `""` (generic Retención), or `None` (unrecognised / not a withholding). `tax_label` is refactored to call it (one parser, not two). Two predicates on top, both honoring the name-first order used by compute_breakdown:978-984 and iva.py:335-345 (a name in CHARGE_LABELS or starting `shp_` is never a withholding):
- `is_recoverable_withholding(charge_type, charge_name) -> bool`: `type == "tax"` and kind == `"sirtac"`.
- `is_debitos_creditos(charge_type, charge_name) -> bool`: `type == "tax"` and kind == `"collector"`.
Plus aggregate helpers over seller charges: `recoverable_withholding_total(seller_charges) -> Decimal` and `debitos_creditos_total(seller_charges) -> Decimal`, both summing `net_amount(charge)` (so refunds are handled for free: add back / double only amount − refunded). All exported in `__all__` (breakdown_service.py:165).
**Alternatives**: name lists / `startswith("tax_withholding_sirtac-")` duplicated in iva.py (rejected: both modules' docstrings forbid parallel lists; `sirtac_sobretasa` shares the prefix and a naive startswith would misclassify it); a separate classifier module (rejected: tax_label's parsing tables live here and must not fork).
**Rationale**: `sirtac` vs `sirtac_sobretasa` is decided by the same `kind_slug` that already labels them; one parser means label and treatment can never disagree. Captured names in tests/fixtures/ml_charges/tax_charge_names.json cover every shape.

### D2 — Neto (R1) inside payment_effective_net
**Choice**: `payment_effective_net` (breakdown_service.py:842) returns `current_result + recoverable_withholding_total(seller_charges)`. Both branches (no refund at :852 and refund at :857) add it. Signature unchanged; docstring updated ("ML's net, corrected for refunds, PLUS the non-refunded SIRTAC withholding, which is a recoverable credit, not a cost").
compute_breakdown additionally computes `retenciones_recuperables = Σ recoverable_withholding_total(seller_charges)` over relevant payments (same loop at :965-968) and exposes it on OperationBreakdown as `retenciones_recuperables: Decimal = 0` plus derived `neto_depositado = neto - retenciones_recuperables` (None when neto is None). SIRTAC breakdown lines keep their tax_label concepto but get `origen="recuperable"` (new value); track a `recuperable_labels: set` while filling line_amounts at :982-984 and set origen per label at :1167-1171. OperationBreakdown docstring (:797) extended: `recuperable` lines are shown but NOT subtracted from neto.
**Alternatives**: add the SIRTAC back in each caller (rejected: three places to drift, TestTheTwoPathsToTheNetAgree would be the only guard); new parallel function `payment_neto_con_recuperables` (rejected: the old function would become a trap still imported by iva.py).
**Rationale**: the one shared function is already the agreement mechanism; changing it keeps compute_neto_by_order_ids, compute_breakdown and descomponer_neto equal without touching their loops.

### D3 — IVA split (R2) in descomponer_neto; extra computed ONCE there
**Choice**:
- `ComponenteIVA` (iva.py:124) gains `informativo: bool = False`. Informational components carry their display bruto/base/iva (passthrough, alicuota None) but are EXCLUDED from `suma_bruto` and from `neto_sin_iva`.
- In the `charge.type == "tax"` branch (iva.py:345), if `is_recoverable_withholding(...)` the component is appended with `informativo=True`.
- After the charge loop, `extra = debitos_creditos_total(seller_charges)` (computed once, the only producer). If `extra != 0`, append `ComponenteIVA(concepto=CONCEPTO_DEBITOS_CREDITOS_RETIRO = "Impuesto a los débitos y créditos (retiro)", alicuota=None, bruto=-extra, base=-extra, iva=0)`.
- Reconciliation (iva.py:383-385): `suma_bruto = Σ bruto of non-informativo components` (includes the extra); `objetivo = neto - extra`; `diferencia = objetivo - suma_bruto`; `reconcilia = diferencia == 0`. `neto_sin_iva = Σ base of non-informativo` when confiable. So the extra lowers neto_sin_iva but never displayed neto.
- `DescomposicionNeto` gains `debitos_creditos_retiro: Decimal = 0` (for API/tests) and `base_venta_sin_iva: Optional[Decimal] = None` (D4).
- Module docstring section "Reconciliation is EXACT (D12)" rewritten: invariant is `sum(non-informational bruto) == neto - debitos_creditos_retiro`.
**Alternatives**: put the SIRTAC in a parallel list instead of a flag (rejected: renderer/order would split; a flag keeps index order and one list); compute the extra in compute_breakdown too (rejected: displayed neto must not change; one producer).
**Rationale**: neto grows by SIRTAC and the SIRTAC component stops contributing — equal and opposite, so reconcilia holds; the extra is added on both sides of the invariant (target and components), so it lowers neto_sin_iva only.

### D4 — Varios base inside the bulk pipeline (R3)
**Choice**:
- descomponer_neto computes `base_venta_sin_iva = Σ base of CONCEPTO_VENTA_ITEM components` in the per-costo loop (iva.py:269-299). It is `None` when: no relevant payments (existing early return), the order has no items, or any of `RAZON_ITEM_SIN_COSTO_CONGELADO`, `RAZON_ITEM_SIN_CANTIDAD`, `RAZON_COSTO_SIN_ITEM` fired. It does NOT depend on `reconcilia` (goods base is independent of charges); a refunded sale is already None via neto_sin_iva.
- `DeduccionResolver.base` (deducciones.py:65) becomes `"neto" | "corriente" | "venta_sin_iva"`; docstring (:56-60) documents the new identifier.
- `calcular_total_gauss(db, order_ids, neto_sin_iva_by_order, *, venta_sin_iva_by_order: Dict[int, Optional[Decimal]])` — required keyword-only (explicit at every caller; no silent default). Objective selection at deducciones.py:485 becomes a small mapping: `"neto" -> neto_sin_iva`, `"corriente" -> total`, `"venta_sin_iva" -> venta_sin_iva_by_order.get(order_id)`.
- `VariosDeduccion.base = "venta_sin_iva"`; `resolve_bulk` unchanged (still returns the RATE, es_porcentaje=True, orden 3 = last in chain). Docstring rewritten: pct × Σ item price without IVA at each item's own frozen rate (mixed-rate packs), same bases the IVA "Venta" components show; subtracted at the end of the chain; retain the note that `pricing_calculator.calcular_comision_ml_total`/`varios_porcentaje` is a separate forward-pricing estimate and is untouched; drop the old "base neto" example and the "matches calcular_comision_ml_total" claim.
- Callers: persistir_total_gauss (deducciones.py:620-622), router listar_ventas (ml_ventas_ops.py:982-984), obtener_operacion (:1193-1195) build `venta_sin_iva_by_order = {oid: d.base_venta_sin_iva ...}` from the descomposiciones they already have. Zero new queries.
**Alternatives**: resolver returns the AMOUNT and queries costos itself (rejected: a second query per page on MlOrderItemCosto and a second rounding path that could disagree with the drawer); use MlOrderItemOps.unit_price (rejected per binding choice: no per-item iva_pct there); pass the whole DescomposicionNeto map (rejected: deducciones imports iva locally to avoid a cycle, deducciones.py:614).

### D5 — Unknown varios base
**Choice**: in calcular_total_gauss, for a percentage resolver: if `raw == 0` → `monto = Decimal("0")` regardless of base (zero percent of anything is zero — preserves "no version configured = 0", deducciones.py:337-346, so an order without frozen costs is not newly blocked by an unconfigured %). Else if the objective is None → `monto = None` → the chain blocks with `("varios", None, None)` in `lineas` and `blocking_codes == ["varios"]` → `total_gauss=None`, `provisional=False` (not the Flex exception). Never a 0 base. In practice costo_mercaderia is also None in that case (same missing frozen row), so the operator already sees the cost link unresolved; varios adds its own unresolved link, which the drawer already renders as "—" (DesgloseDrawer.jsx:547).
**Rationale**: consistent with module rule "None propagates, NEVER a lying zero"; the rate-0 short circuit is the only case where the answer is known without the base.

### D6 — API and frontend
Router (ml_ventas_ops.py):
- `BreakdownLineSummary.origen` docstring (:179-194): add `"recuperable"` = recoverable withholding (SIRTAC), shown, NOT subtracted from neto.
- `OperationBreakdownSummary` (:212): add `neto_depositado: Optional[float]`, `retenciones_recuperables: Optional[float]` (None when neto None); `from_domain` maps them.
- `IvaComponenteSummary` (:277): add `informativo: bool = False`.
- `DescomposicionIvaSummary` (:288): add `debitos_creditos_retiro: float = 0`, `base_venta_sin_iva: Optional[float] = None`.
All additive.
Frontend compatibility check (verified): DesgloseDrawer.jsx:266 filters ONLY `origen !== 'propio'`, so an unknown `recuperable` line would render in the subtraction list next to a neto that no longer subtracts it; and :407-421 renders every componente with base/IVA, so an `informativo` component would read as part of neto sin IVA. Both mislead on a money path → the minimal FE guard MOVES INTO PR1: (a) split `lines` into `lines` (not propio/recuperable) and `recuperables` (origen === 'recuperable'), render recuperables as a muted row "<concepto> · se recupera a fin de mes (no se descuenta)" after the list; (b) in the IVA list, `componente.informativo` rows render muted with "(informativo)" and no "base/IVA" figures. The retiro component needs no FE change (regular alicuota-null row, concept label comes from backend).
PR3 adds the Neto sub-line under the "Neto" total (DesgloseDrawer.jsx:394-397): when `retenciones_recuperables > 0`, "ML depositó {formatAmount(neto_depositado)} · SIRTAC {formatAmount(retenciones_recuperables)} se recupera a fin de mes"; CSS module class for muted sub-line (tokens only), plus a "% de varios" hint showing base (`base_venta_sin_iva`) if desired.

## Data Flow
    MlPaymentCharge ──classifier(D1)──┬─> payment_effective_net (+SIRTAC) ─> neto (3 paths equal)
                                      ├─> compute_breakdown lines (origen api|recuperable|propio)
                                      └─> descomponer_neto: SIRTAC informativo, +retiro(-extra),
                                            target neto-extra ─> neto_sin_iva, base_venta_sin_iva
    MlOrderItemCosto ─> Venta comps ─> base_venta_sin_iva ─┐
    neto_sin_iva ──────────────────────────────────────────┴─> calcular_total_gauss
        costo -> flex -> varios(rate × venta_sin_iva) ─> total_gauss (live) / persistir (sort key)

## File Changes
| File | Action | PR |
|---|---|---|
| backend/app/services/ml_ventas_desglose/breakdown_service.py | Modify: withholding_kind + predicates + totals; tax_label uses it; payment_effective_net add-back; OperationBreakdown fields; recuperable origen | 1 |
| backend/app/services/ml_ventas_desglose/iva.py | Modify: informativo flag, retiro component, target neto-extra, docstring, debitos_creditos_retiro; base_venta_sin_iva | 1 (base in 2) |
| backend/app/routers/ml_ventas_ops.py | Modify: summaries additive fields (PR1); pass venta_sin_iva_by_order (PR2) | 1,2 |
| frontend/src/components/DesgloseDrawer.jsx (+ .test.jsx, .module.css) | Minimal guard (PR1); Neto sub-line + polish (PR3) | 1,3 |
| backend/app/services/ml_ventas_desglose/deducciones.py | Modify: base "venta_sin_iva", calcular_total_gauss kwarg, rate-0 short-circuit, Varios docstring, persistir caller | 2 |
| backend/tests/services/ml_ventas_desglose/test_{tax_labels,breakdown_service,iva,deducciones}.py | Modify/add | 1,2 |
No migration, no model/schema change, no cron.

## Interfaces
```python
def withholding_kind(charge_name: Optional[str]) -> Optional[str]: ...
def is_recoverable_withholding(charge_type: Optional[str], charge_name: Optional[str]) -> bool: ...
def is_debitos_creditos(charge_type: Optional[str], charge_name: Optional[str]) -> bool: ...
def recoverable_withholding_total(seller_charges: Sequence[MlPaymentCharge]) -> Decimal: ...
def debitos_creditos_total(seller_charges: Sequence[MlPaymentCharge]) -> Decimal: ...
@dataclass(frozen=True) class ComponenteIVA: ...; informativo: bool = False
@dataclass(frozen=True) class DescomposicionNeto: ...; debitos_creditos_retiro: Decimal = Decimal("0"); base_venta_sin_iva: Optional[Decimal] = None
def calcular_total_gauss(db, order_ids, neto_sin_iva_by_order, *, venta_sin_iva_by_order: Dict[int, Optional[Decimal]]) -> Dict[int, TotalGaussResultado]
```

## Worked example (fixture = stored values of order 2000018567320906, payment 180131165380)
Charges: coupon_rebate 41679.67 type coupon (non-seller), meli_percentage_fee 74676.08, shp_cross_docking 15190.00, tax_withholding_sirtac-caba 1792.23, tax_withholding_collector-debitos_creditos 3584.45 (all refunded 0); net_received 502165.91; shipping_amount 0; item MLA2060835678 qty 1, frozen precio 597408.67, iva 21.
- neto = 502165.91 + 1792.23 = 503958.14; neto_depositado 502165.91; retenciones_recuperables 1792.23.
- Components: Venta +597408.67 (base 493726.17 / iva 103682.50); Cargo por vender −74676.08 (base −61715.77); Envíos (Colecta) −15190.00 (base −12553.72); débitos y créditos −3584.45 passthrough; SIRTAC CABA −1792.23 informativo; retiro −3584.45 passthrough.
- Σ non-informativo bruto = 500373.69 = 503958.14 − 3584.45 → reconcilia True, diferencia 0.
- neto_sin_iva = 493726.17 − 61715.77 − 12553.72 − 3584.45 − 3584.45 = 412287.78.
- base_venta_sin_iva = 493726.17; Varios 5% = 24686.31 (ROUND_HALF_UP of 24686.3085).

## Testing Strategy (Strict TDD, RED first)
PR1 — add:
- test_tax_labels.py `TestWithholdingKindClassifier`: every name in tax_charge_names.json maps to the expected kind (sirtac-* → "sirtac", sirtac_sobretasa-* → "sirtac_sobretasa", collector → "collector", bare tax_withholding-<prov> → "", unknown → None); tax_label outputs unchanged (existing 9 tests stay green = refactor proof); a fee-named `type=tax` charge is not a withholding.
- test_iva.py `TestTheWorkedExampleOrder` (fixture above, built with existing helpers): exact neto, informativo SIRTAC, retiro component, reconcilia, neto_sin_iva 412287.78.
- `TestSirtacRefundOnlyNonRefundedPortion`: SIRTAC amount X refunded Y → add-back X−Y (both compute_breakdown and descomponer_neto); same for débitos extra.
- `TestSobretasaAndGenericRetencionStillSubtract`: sirtac_sobretasa-jujuy and tax_withholding-santa_fe not added back, not informativo.
- `TestDebitosExtraWithoutSirtac`: collector-only order gets the retiro component and reconciles.
- test_breakdown_service.py: extend `TestTheTwoPathsToTheNetAgree` (:449) with SIRTAC (+ partial refund) cases; `TestRecoverableLineOrigen`: SIRTAC line origen "recuperable", others "api"; neto_depositado/retenciones_recuperables.
- test_iva.py `TestTheThirdPathToTheNetAgrees` (:568): add a SIRTAC case.
PR1 — rewrite/extend: `test_ml_funded_coupon_is_already_inside_the_item_price` (:427) keep, now also asserts exact values (or superseded by TestTheWorkedExampleOrder); `TestWithholdingTypeTaxNotSplit` (:195) add `informativo is True` for the sirtac name and a sobretasa counterpart; `TestWithholdingPredicateReusedNotDuplicated` (:217) keep reconcilia and assert informativo exactly on sirtac-* names. Frontend: DesgloseDrawer.test.jsx — recuperable line not in the subtraction list but visible as informational; informativo componente muted without base/IVA.
PR2 — deducciones: rewrite `TestVariosDeduccion.test_percentage_applies_over_neto_sin_iva` (:272) → `..._over_goods_without_iva`; add mixed-rate pack (10.5 + 21) base per item; unknown base with rate>0 blocks (`("varios", None, None)`, total None, provisional False); rate 0 with unknown base → monto 0, not blocking; worked-example varios 24686.31 via persistir_total_gauss end-to-end; iva test for base_venta_sin_iva None per razon. Update the 14 calcular_total_gauss test calls with the new kwarg.
PR3 — DesgloseDrawer.test.jsx: sub-line text with formatted amounts; absent when retenciones_recuperables is 0/null.
Run: backend pytest tests/services/ml_ventas_desglose (uv venv), ruff format app/ tests/; frontend pnpm vitest.

## Threat Matrix
N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout
No migration. PR order 1 → 2 → 3, each safe alone: PR1 changes neto+IVA atomically (reconciliation never breaks) and ships the FE guard; PR2 only changes Varios; PR3 is presentation. Stored total_gauss rows computed before deploy stay on old rules until something marks them stale or the ventas-ml-rediseno worker recomputes via formula_version (accepted: column is a sort key; displayed values are live). Listing neto (compute_neto_by_order_ids) changes immediately with PR1. Rollback: revert in reverse order.

## Open Questions
- None blocking. Assumption to validate in prod read-only: divergence rate between MlOrderItemCosto.precio_unitario and MlOrderItemOps.unit_price (Varios follows the frozen snapshot by decision).

## PR slicing (auto-chain, ~400 lines each)
1. Classifier + neto add-back + IVA informativo/retiro + router additive fields + minimal FE guard + tests.
2. base_venta_sin_iva + Varios base + calcular_total_gauss kwarg + docstrings + tests.
3. Neto sub-line + styles + FE tests.

## Key Learnings
- The current drawer only filters origen 'propio' (DesgloseDrawer.jsx:266) and renders every IVA componente with base/IVA — a backend-first ship would mislead, so the FE guard belongs in PR1.
- payment_effective_net is already the single shared net function for all three paths; putting R1 there makes path agreement structural.
- Rate-0 short-circuit is required, or unconfigured Varios would newly block total_gauss on every order lacking frozen costs.
- calcular_total_gauss has 14 test call sites + 3 prod; required kwarg is explicit churn, accepted.
