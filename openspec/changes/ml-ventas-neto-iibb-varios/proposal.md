# Proposal: ML sales net — SIRTAC add-back, débitos/créditos withdrawal tax, "% de varios" on net-of-IVA amount

## Intent
The ML sales money path misstates the seller's economics in three ways:
1. IIBB SIRTAC withholding (`tax_withholding_sirtac-<prov>`) is subtracted from Neto, but it is a recoverable tax credit (recovered at month end), not a cost.
2. The débitos y créditos tax (`collector-debitos_creditos`) is paid again when money is withdrawn from Mercado Pago; that second payment is not reflected anywhere.
3. "% de varios" (`VariosDeduccion`) uses base = `neto_sin_iva`; the business rule is percentage × operation amount WITHOUT IVA.
Why now: must land BEFORE the paused `ventas-ml-rediseno`, which will store Total Gauss as source of truth — freezing wrong numbers there would be far costlier to fix.

## Final binding business rules (override the exploration)
- R1 SIRTAC withholding: neto = ML net_received + non-refunded SIRTAC (`net_amount = amount - refunded`). Still shown as an informational line (not subtracted). `sirtac_sobretasa`, `collector-debitos_creditos`, and generic "Retención" (no regime) KEEP subtracting.
- R2 Débitos/créditos doubled: extra IVA-free component equal to the non-refunded débitos/créditos charge, labeled "Impuesto a los débitos y créditos (retiro)". Lowers `neto_sin_iva` (thus Total Gauss) but NOT displayed Neto. New invariant: sum(components) == neto − extra_debitos_creditos.
- R3 Varios: amount = pct × Σ_item (precio_unitario × qty / (1 + iva_pct_item)); subtracted at the end of the Total Gauss chain from neto_sin_iva. Per-item own rate for mixed-rate packs.
- R4 Label: keep "Neto" + sub-line "ML depositó $X · SIRTAC $Y se recupera a fin de mes".

## Scope
### In Scope
- `payment_effective_net` (breakdown_service.py:842): add back non-refunded SIRTAC withholding; shared by `compute_breakdown` and `compute_neto_by_order_ids` so both paths stay equal.
- `descomponer_neto` / `ComponenteIVA` (iva.py): SIRTAC component becomes informational (0 contribution to suma_bruto/neto_sin_iva, display amount kept); new extra débitos/créditos IVA-free component; reconciliation invariant updated to neto − extra.
- `VariosDeduccion` (deducciones.py:299) base switched to Σ goods "Venta" bases (net of IVA) plumbed into `calcular_total_gauss`/`persistir_total_gauss`; docstring rewritten (keep note that `calcular_comision_ml_total` in pricing_calculator.py is a separate forward-pricing feature, untouched).
- Router response (`routers/ml_ventas_ops.py`) + `DesgloseDrawer.jsx`: SIRTAC shown via the existing "shown but not subtracted" `origen` mechanism (new origen value, not "propio"); withdrawal-tax line; Neto sub-line.
- Post-deploy recompute of stored `total_gauss` without a new cron: one-off Alembic data migration (or script) setting `total_gauss_stale=True` for all rows; the EXISTING sweep (`sweep_service.py:1788` → `refrescar_total_gauss_pendientes`, 500/pass) drains it.
### Out of Scope
- `pricing_calculator.calcular_comision_ml_total` / `varios_porcentaje` forward-pricing.
- Any new cron/scheduler; `ventas-ml-rediseno` itself.
- Changing treatment of `sirtac_sobretasa`, generic Retención, or other withholdings.
- Month-end SIRTAC recovery reconciliation/reporting.

## Capabilities
### New Capabilities
- None
### Modified Capabilities
- `ml-ventas-neto`: Neto adds back non-refunded SIRTAC withholding; both net paths agree.
- `ml-ventas-iva-breakdown`: SIRTAC informational component; extra IVA-free débitos/créditos withdrawal component; invariant sum == neto − extra.
- `ml-ventas-total-gauss`: Varios base = operation amount without IVA (per-item rate); stored total_gauss refreshed post-deploy via existing sweep.
- `ml-ventas-desglose-ui`: informational SIRTAC line, withdrawal-tax line, Neto sub-line.
(No openspec/specs dir — engram mode; names are proposed.)

## Approach
- Single classifier for "SIRTAC withholding" vs "SIRTAC sobretasa" vs "débitos/créditos" reused by breakdown_service and iva.py (avoid drift between paths).
- Varios base source: use frozen `MlOrderItemCosto.precio_unitario`/`iva_pct` — the SAME inputs that build the IVA split "Venta" components. Justification: (a) R3 defines the base as "the base of the goods Venta components", so reusing them makes base ≡ what the drawer shows, by construction; (b) per-item iva_pct is only available there, required for mixed-rate packs; (c) the bulk total_gauss pipeline already runs descomponer_neto, so no new query on MlOrderItemOps. Tradeoff: if cost snapshot price diverges from MlOrderItemOps.unit_price, Varios follows the snapshot — acceptable and consistent with the IVA split; design should confirm the divergence rate. Expose it as a field on the descomponer_neto result (e.g. `base_venta_sin_iva`) and carry it next to neto_sin_iva in `neto_sin_iva_by_order`.
- Atomicity: R1 (neto) and R2 (IVA split) change the reconciliation — neto change and IVA split change ship in the SAME PR, else every order reads "no reconcilia".
- Strict TDD: RED first, using real captured charge shapes (order 2000018567320906 and a SIRTAC+refund case from `backend/tests/fixtures/ml_charges`); no invented fixtures.

## PR slicing (auto-chain, ~400 lines, each safe alone)
1. Backend neto + IVA split (R1+R2 together) incl. TestTheTwoPathsToTheNetAgree, reconciliation tests; API emits new fields additively (frontend ignores unknown origen until PR 3 — must verify current drawer does not subtract/duplicate an unknown origen; if it would, fold the minimal FE filter into PR1).
2. Varios base (R3) + docstrings + total_gauss plumbing.
3. Frontend drawer lines + Neto sub-line (R4).
4. Stale-mark data migration (last, so recompute uses all new rules). May fold into PR 2 if small; it must run after PR1 and PR2 are deployed.

## Affected Areas
| Area | Impact | Description |
|---|---|---|
| backend/app/services/ml_ventas_desglose/breakdown_service.py | Modified | payment_effective_net SIRTAC add-back |
| backend/app/services/ml_ventas_desglose/iva.py | Modified | informational component, withdrawal-tax component, invariant, base_venta_sin_iva |
| backend/app/services/ml_ventas_desglose/deducciones.py | Modified | VariosDeduccion base + docstring, total_gauss plumbing |
| backend/app/routers/ml_ventas_ops.py | Modified | response lines/origen |
| frontend DesgloseDrawer.jsx (+ VentasML.jsx if Neto shown) | Modified | lines + sub-line |
| backend/alembic/versions/* | New | one-off total_gauss_stale=True |
| backend/tests/services/ml_ventas_desglose/* | Modified | ~134 tests, several rewritten |

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Reconciliation breaks (neto vs components) | High if split | R1+R2 in one PR; invariant test on real data |
| Two net paths diverge | Med | shared function + TestTheTwoPathsToTheNetAgree |
| SIRTAC misclassified vs sobretasa/generic Retención | Med | explicit classifier tests per captured name |
| Varios source divergence (cost snapshot vs item price) | Low-Med | design measures divergence; documented choice |
| Stale backlog drain time (all rows / 500 per pass) | Med | size from prod count × sweep cadence; values temporarily old-rule until drained |
| Users read Neto > deposit as error | Med | R4 sub-line |
| ventas-ml-rediseno starts before this lands | Med | explicit dependency |

## Rollback Plan
Revert PRs in reverse order (each standalone). After reverting backend rules, re-run the same stale-mark migration/script so the existing sweep recomputes total_gauss under the old rules. No schema changes, so no destructive downgrade; the data migration's downgrade is a no-op.

## Dependencies
- Must merge and deploy BEFORE `ventas-ml-rediseno` resumes.
- Existing sweep job (`sweep_service.py` → `refrescar_total_gauss_pendientes`) must be running.

## Success Criteria
- [ ] Order 2000018567320906 (monto 597408.67; fee 74676.08; shp_cross_docking 15190; SIRTAC CABA 1792.23; débitos/créditos 3584.45; ML net 502165.91): Neto = 503958.14; SIRTAC 1792.23 shown as informational; extra "Impuesto a los débitos y créditos (retiro)" 3584.45 lowers neto_sin_iva by an additional 3584.45; reconcilia=True with sum(components) == neto − 3584.45; Varios base = 597408.67/1.21 = 493726.17, at 5% = 24686.31 subtracted at end of Total Gauss chain.
- [ ] Refunded SIRTAC/débitos-créditos: only non-refunded portion is added back / doubled.
- [ ] sobretasa and generic Retención still subtract.
- [ ] Mixed-rate pack: Varios base uses each item's own iva_pct.
- [ ] compute_breakdown and compute_neto_by_order_ids agree.
- [ ] Zero orders report "no reconcilia" in prod after deploy that did not before.
- [ ] All stored total_gauss recomputed via existing sweep; no new cron.
- [ ] Drawer shows "Neto" with sub-line "ML depositó $X · SIRTAC $Y se recupera a fin de mes".

## Open questions for orchestrator
- Confirm Varios source = frozen MlOrderItemCosto (recommended) vs MlOrderItemOps.unit_price.
- Does R2 apply when there is no SIRTAC / for every order with débitos/créditos (assumed: every order with a non-refunded débitos/créditos charge)?
