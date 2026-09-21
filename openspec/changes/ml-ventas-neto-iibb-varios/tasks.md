# Tasks: ML sales net — SIRTAC add-back, débitos/créditos withdrawal tax, Varios on goods without IVA

Change: ml-ventas-neto-iibb-varios. Sources: proposal #2111, spec #2114, design #2115.
Branch off origin/main: `fix/iva-cupon-doble-conteo` is unrelated prior work already on this worktree — create a NEW branch from origin/main for this change, e.g. `feat/ml-ventas-neto-iibb-varios`.
delivery_strategy: auto-chain. chain_strategy (stacked-to-main vs feature-branch-chain): NOT YET CHOSEN — pending, ask before creating PR2 (or PR1 if it alone crosses budget with follow-on work queued).
Strict TDD: RED (named failing test) → GREEN (implementation) → REFACTOR, per task, backend pytest / frontend pnpm vitest.

## Binding adjustment applied in this phase (per orchestrator instruction)

Design originally placed the Neto sub-line ("ML depositó $X · SIRTAC $Y se recupera a fin de mes") in PR3. Per orchestrator's binding adjustment for this phase, the sub-line (and the neto_depositado/retenciones_recuperables fields it needs) are ALREADY required by spec's `ml-ventas-desglose-ui` requirement and MUST ship in PR1 so the drawer's Neto never rises without its explanation in the same deploy. Moved: PR3.T1/T2 → PR1.T9/T10 below. Fields `neto_depositado`/`retenciones_recuperables` on `OperationBreakdownSummary` were already scheduled for PR1 in design D6, so only the JSX sub-line + its test + CSS move.

**Result: PR3 is empty of required work.** The only remaining design PR3 item ("% de varios" hint showing `base_venta_sin_iva`, design D6, listed "if desired") is NOT mandated by any spec scenario — dropped or folded as an optional line into PR2 (`base_venta_sin_iva` already lands in PR2's `DescomposicionIvaSummary`). Recommendation: **do not open PR3**; if desired, add the varios-hint as a small optional addendum to PR2. Confirm before apply.

**Flag — product question, not resolved here:** the spec's `ml-ventas-desglose-ui` requirement text only describes the DRAWER sub-line. Design's file table does not touch `VentasML.jsx` (the listing). The listing also shows Neto per row (per design's Data Flow: "Listing neto (compute_neto_by_order_ids) changes immediately with PR1"), so a row's Neto number jumps the same day PR1 ships, with no inline explanation — only the drawer (opened per-order) carries the sub-line/tooltip. Whether the listing needs its own tooltip/indicator is NOT specified and NOT designed. This is a product decision for the user/orchestrator before PR1 is considered fully closing the UX gap; PR1 tasks below do NOT add a listing-level indicator absent that decision.

## PR1 — Classifier + Neto add-back + IVA informativo/retiro + router additive fields + FE guard + Neto sub-line

Files: `backend/app/services/ml_ventas_desglose/breakdown_service.py`, `backend/app/services/ml_ventas_desglose/iva.py`, `backend/app/routers/ml_ventas_ops.py` (additive fields only), `frontend/src/components/DesgloseDrawer.jsx` (+`.test.jsx`, `.module.css`), backend tests in `backend/tests/services/ml_ventas_desglose/test_tax_labels.py`, `test_breakdown_service.py`, `test_iva.py`.

Satisfies spec requirements: `ml-ventas-neto` (Displayed Neto computation), `ml-ventas-iva-breakdown` (IVA component reconciliation), `ml-ventas-desglose-ui` (SIRTAC/withdrawal/Neto sub-line display).

Sequential within PR1 (each step depends on classifier existing); PR1 itself can run in parallel with nothing (it is the foundation PR2/PR3 depend on).

- [x] **PR1.T1** [seq] RED: `test_tax_labels.py::TestWithholdingKindClassifier` — every name in `tests/fixtures/ml_charges/tax_charge_names.json` maps to expected kind (`sirtac-*`→`"sirtac"`, `sirtac_sobretasa-*`→`"sirtac_sobretasa"`, `collector`→`"collector"`, bare `tax_withholding-<prov>`→`""`, unknown→`None`); a fee-named `type=tax` charge is not a withholding. Confirm test fails (function doesn't exist).
  → GREEN: implement `withholding_kind()` in `breakdown_service.py` next to `tax_label`; refactor `tax_label` to call it (existing 9 `tax_label` tests must stay green — refactor proof, run them as part of GREEN).
  → REFACTOR: dedupe parsing, update `__all__`.
- [x] **PR1.T2** [seq, depends T1] RED: predicates/aggregates tests — `is_recoverable_withholding`, `is_debitos_creditos`, `recoverable_withholding_total`, `debitos_creditos_total` (refund-aware, sum `net_amount`).
  → GREEN: implement per D1. → REFACTOR: export in `__all__`.
- [x] **PR1.T3** [seq, depends T2] RED: `test_iva.py::TestTheWorkedExampleOrder` using order 2000018567320906 fixture (Neto 503958.14, SIRTAC informativo 1792.23, retiro component 3584.45, reconcilia True, `sum(bruto)`=500373.69, neto_sin_iva 412287.78).
  → GREEN: `payment_effective_net` add-back (D2); `ComponenteIVA.informativo` flag, retiro component, reconciliation target `neto - extra` (D3).
- [x] **PR1.T4** [seq] RED: `TestSirtacRefundOnlyNonRefundedPortion` (partial + full refund cases, both `compute_breakdown` and `descomponer_neto`) and matching débitos-extra refund case.
  → GREEN: verify `net_amount`-based sums already cover it (should already pass structurally; add missing edge handling if not).
- [x] **PR1.T5** [seq] RED: `TestSobretasaAndGenericRetencionStillSubtract` (sirtac_sobretasa-jujuy, tax_withholding-santa_fe: not added back, not informativo, subtracted unchanged) + `TestDebitosExtraWithoutSirtac` (collector-only order still gets retiro component and reconciles).
  → GREEN: confirm classifier scoping is correct (kind `""`/`"sirtac_sobretasa"` excluded from add-back).
- [x] **PR1.T6** [seq] RED: extend `test_breakdown_service.py::TestTheTwoPathsToTheNetAgree` (line ~449) with SIRTAC + partial-refund cases; new `TestRecoverableLineOrigen` (SIRTAC line `origen == "recuperable"`, others `"api"`; `neto_depositado`/`retenciones_recuperables` values match worked example).
  → GREEN: `compute_breakdown` origen tagging + new `OperationBreakdown` fields (D2).
- [x] **PR1.T7** [seq] RED: extend `test_iva.py::TestTheThirdPathToTheNetAgrees` (line ~568) with a SIRTAC case (three-path agreement).
  → GREEN: none expected beyond T3–T6 (regression guard).
- [x] **PR1.T8** [seq] Update existing tests per design: `test_ml_funded_coupon_is_already_inside_the_item_price` (asserts exact values or is superseded by T3); `TestWithholdingTypeTaxNotSplit` add `informativo is True` assertion for sirtac name + sobretasa counterpart; `TestWithholdingPredicateReusedNotDuplicated` assert `informativo` exactly on `sirtac-*` names.
- [x] **PR1.T9** [seq, depends T6] Router additive fields — `BreakdownLineSummary.origen` docstring add `"recuperable"`; `OperationBreakdownSummary` gains `neto_depositado`, `retenciones_recuperables` (None-safe); `IvaComponenteSummary` gains `informativo: bool = False`; `DescomposicionIvaSummary` gains `debitos_creditos_retiro: float = 0`, `base_venta_sin_iva: Optional[float] = None` (value populated in PR2, field exists now per D6). No new tests strictly required beyond existing router serialization tests if present — verify with `ruff check` + existing router test suite; add a minimal serialization test if none covers new fields.
- [x] **PR1.T10** [seq, depends T9] RED (frontend, `DesgloseDrawer.test.jsx`, vitest): (a) recuperable line (SIRTAC) rendered as a muted informational row after the subtraction list, excluded from the amount subtracted from Neto; (b) `componente.informativo` IVA rows render muted, "(informativo)", no base/IVA figures; (c) **[moved from design's PR3]** Neto sub-line "ML depositó {neto_depositado} · SIRTAC {retenciones_recuperables} se recupera a fin de mes" renders under the Neto total when `retenciones_recuperables > 0`, absent when 0/null, using the worked-example formatted amounts.
  → GREEN: `DesgloseDrawer.jsx` — split `lines`/`recuperables` (origen splitting logic), `informativo` styling, Neto sub-line block; `.module.css` muted-row token class (moved up from design PR3).
- [x] **PR1.T12** [seq, depends T10] RED first (frontend, `VentasML.test.jsx`, vitest): the listing Neto cell shows the tooltip "MP $X · SIRTAC $Y" when `retenciones_recuperables > 0`, and nothing when 0/null. NOTE: the listing API (`SaleListItem`/`SaleGroup`, fed by `compute_neto_by_order_ids`) does NOT carry `neto_depositado`/`retenciones_recuperables` today. Add them in bulk (same two queries, no per-row query), plus a backend RED test; for packs, sum the members (all-or-nothing, like `group_neto`).
- [x] **PR1.T11** [seq] Verification: `ruff format app/ tests/`, `ruff check app/ tests/`, `pytest backend/tests/services/ml_ventas_desglose` (uv venv), `pnpm lint`, `pnpm vitest run` (frontend).

## PR2 — Varios base (venta_sin_iva) + calcular_total_gauss kwarg

Files: `backend/app/services/ml_ventas_desglose/iva.py` (add `base_venta_sin_iva` computation — additive to PR1's `descomponer_neto` changes, rebased on PR1), `backend/app/services/ml_ventas_desglose/deducciones.py`, `backend/app/routers/ml_ventas_ops.py` (pass `venta_sin_iva_by_order`), tests in `test_iva.py`, `test_deducciones.py`.

Satisfies spec requirement: `ml-ventas-total-gauss` ("% de varios" deduction base).

Depends on PR1 (reuses `descomponer_neto`/classifier). Sequential.

- [ ] **PR2.T1** [seq] RED: `test_iva.py` — `base_venta_sin_iva` computed as Σ base of `CONCEPTO_VENTA_ITEM` components in the worked example (493726.17); `None` when no relevant payments / no items / `RAZON_ITEM_SIN_COSTO_CONGELADO` / `RAZON_ITEM_SIN_CANTIDAD` / `RAZON_COSTO_SIN_ITEM` fires; independent of `reconcilia`.
  → GREEN: add `base_venta_sin_iva` field + computation to `DescomposicionNeto`/`descomponer_neto` per D4.
- [ ] **PR2.T2** [seq, depends T1] RED: mixed-rate pack test — items at 21% and 10.5% each divided by their own `(1 + rate)` before summing (no cross-item rate use).
  → GREEN: confirm per-item loop already does this (D4); fix if it aggregates before dividing.
- [ ] **PR2.T3** [seq] RED: `test_deducciones.py` — rewrite `TestVariosDeduccion.test_percentage_applies_over_neto_sin_iva` → `..._over_goods_without_iva`; `DeduccionResolver.base` accepts `"venta_sin_iva"`; `VariosDeduccion.base = "venta_sin_iva"`.
  → GREEN: implement per D4 (resolver base literal, objective-selection mapping).
- [ ] **PR2.T4** [seq, depends T3] RED: `calcular_total_gauss` signature test — new required keyword-only `venta_sin_iva_by_order: Dict[int, Optional[Decimal]]`; call without it fails (TypeError/explicit).
  → GREEN: update signature per D4; update the 14 existing test call sites + 3 prod call sites (`persistir_total_gauss` deducciones.py:620-622, `listar_ventas` ml_ventas_ops.py:982-984, `obtener_operacion` :1193-1195) to build and pass `venta_sin_iva_by_order` from the descomposiciones already in hand (zero new queries).
- [ ] **PR2.T5** [seq] RED: rate-0 short-circuit — `raw == 0` on percentage resolver → `monto = Decimal("0")` even when base is `None` (unconfigured % stays non-blocking).
  → GREEN: implement short-circuit ordering per D5 (check rate first, then base).
- [ ] **PR2.T6** [seq, depends T5] RED: unknown base with `rate > 0` → blocks: `("varios", None, None)` in `lineas`, `blocking_codes == ["varios"]`, `total_gauss=None`, `provisional=False` (never a silent 0).
  → GREEN: implement per D5.
- [ ] **PR2.T7** [seq] RED: worked-example end-to-end via `persistir_total_gauss` — Varios 5% × 493726.17 = 24686.31 (`ROUND_HALF_UP`), subtracted at the end of the deduction chain, from `neto_sin_iva` 412287.78.
  → GREEN: regression confirmation (should pass from T1–T6); fix ordering if the varios line isn't last in the chain.
- **PR2.T8** (NOT in scope, not confirmed) [optional, not spec-mandated] Only if the "do not open PR3" recommendation above is confirmed: add an optional "% de varios" base hint (`base_venta_sin_iva`) to the drawer as a small addendum here, with its own RED test. Skip if not confirmed — no spec scenario requires it.
- [ ] **PR2.T9** [seq] Verification: `ruff format app/ tests/`, `ruff check app/ tests/`, `pytest backend/tests/services/ml_ventas_desglose` (uv venv); if T8 included, `pnpm lint` + `pnpm vitest run`.

## PR3 — DISSOLVED (pending confirmation)

Design originally scoped PR3 as "Neto sub-line + styles + FE tests" — fully moved into PR1.T10 per binding adjustment above. No required spec scenario remains for a standalone PR3. Recommend closing this slot; do not create a PR3 branch. If the user wants the optional varios-hint (PR2.T8) done separately instead of folded into PR2, that would become the new PR3 — flag before apply, do not assume.

## Review Workload Forecast

| PR | Est. changed lines (add+del) | Chained PRs recommended | 400-line budget risk | Decision needed before apply |
|----|-------------------------------|--------------------------|------------------------|-------------------------------|
| PR1 | ~380–430 (backend classifier/predicates ~90, payment_effective_net/OperationBreakdown ~60, iva.py informativo+retiro+reconciliation ~70, router additive fields ~30, DesgloseDrawer.jsx+css incl. moved sub-line ~60, backend tests ~90, frontend tests ~40) | Yes — this is the largest PR and the one most likely to brush the 400-line budget once the moved sub-line work is added | **High** — moving PR3's sub-line work into PR1 pushes it right at/over budget; needs `chain_strategy` decision (stacked-to-main vs feature-branch-chain) before this PR is opened, or a further internal split (e.g. backend-only PR1a + FE-guard PR1b) | 1) Confirm chain_strategy. 2) Confirm PR1 stays one PR despite likely crossing ~400 lines, or should split backend/frontend. |
| PR2 | ~220–280 (iva.py base_venta_sin_iva ~40, deducciones.py resolver/signature/short-circuit ~60, 3 prod call-site + 14 test call-site kwarg churn ~80, tests ~60–100) | No — fits comfortably under budget alone | Low | Confirm whether PR2.T8 (optional varios hint) is in scope — changes estimate by ~40–60 lines if yes. |
| PR3 | 0 (dissolved) | N/A | N/A | Confirm PR3 is not opened; work already redistributed to PR1/PR2. |

## Key Learnings

- **The binding adjustment moving the Neto sub-line into PR1 is a genuine budget risk**: design had already sized PR1 near a full classifier+neto+IVA rewrite; folding in `DesgloseDrawer.jsx` sub-line + CSS + test pushes PR1 close to or over the 400-line review-policy threshold. This is flagged explicitly in the forecast rather than silently absorbed — auto-chain's chain_strategy choice (stacked-to-main vs feature-branch-chain) should be resolved before PR1 is opened, not discovered mid-review.
- **PR3 dissolving to zero required work is a direct, traceable consequence of the orchestrator's binding adjustment**, not a task-phase judgment call — documented so `sdd-apply` doesn't recreate a hollow PR3 out of habit from reading the design doc alone.
- **The listing (VentasML.jsx) Neto-jump-without-explanation gap is flagged, not resolved**: spec text is drawer-specific, design's file table never touches VentasML.jsx, but design's own Data Flow section confirms listing Neto changes the same day PR1 ships. This is surfaced as an explicit product question for confirmation before/along with `sdd-apply`, per the instruction not to invent scope.
- **calcular_total_gauss's required kwarg touches 14 test call sites + 3 prod call sites** (design D4) — sized explicitly in PR2's forecast so the "mechanical but wide" churn isn't mistaken for scope creep during apply.

## Decisions after tasks (2026-09-21)

Later user decisions, applied on top of the tasks above without rewriting them:

- (a) **PR3 is NOT opened.** The "PR3 — DISSOLVED (pending confirmation)" recommendation above is now confirmed: no PR3 branch is created. If the optional varios-hint (PR2.T8) is ever wanted, it ships inside PR2 or a future change, never as a standalone PR3.
- (b) **Listing-level tooltip added to PR1.** The product question flagged above ("the listing (VentasML.jsx) Neto-jump-without-explanation gap") is resolved: the Neto cell in the listing (`VentasML.jsx`) gets a tooltip in PR1, not deferred. New task **PR1.T12** [seq, depends T10] RED (frontend, `VentasML.test.jsx`, vitest, written FIRST/failing before implementation per Strict TDD): the listing's Neto cell renders a tooltip showing the sub-line text (see decision (c) below) whenever `retenciones_recuperables > 0` for that row, using the same `neto_depositado`/`retenciones_recuperables` fields already added to the row/API response; absent when 0/null.
  → GREEN: wire the tooltip onto the Neto cell in `VentasML.jsx`, reusing the existing tooltip mechanism/component already used elsewhere in the listing if one exists, else a minimal tokens-only tooltip.
- (c) **Sub-line and tooltip text changed.** Everywhere the earlier wording "ML depositó $X · SIRTAC $Y se recupera a fin de mes" appears in this tasks file (PR1.T10 item (c), and by reference in PR1.T12 above), the exact required text is now:
  `"MP $X · SIRTAC $Y"`
  where X = `neto_depositado` and Y = `retenciones_recuperables` (same field semantics as before: X = seller's effective net received/deposited amount, Y = non-refunded SIRTAC amount). This wording change applies to BOTH the drawer's Neto sub-line (PR1.T10.c) and the new listing tooltip (PR1.T12). Do not implement the earlier "ML depositó ... se recupera a fin de mes" copy anywhere; it is superseded.
- (d) **Chain strategy: sequential, not stacked.** PR2 is opened only AFTER PR1 is MERGED, branching fresh from `origin/main` at that point (not stacked on PR1's branch). This resolves the "chain_strategy NOT YET CHOSEN" note at the top of this file and the "Confirm chain_strategy" line in the Review Workload Forecast: the chosen strategy is **feature-branch-chain / sequential-from-main**, not stacked-to-main. PR1's likely-over-400-lines risk (see forecast) is accepted as-is under this sequential strategy; no further internal PR1 split was requested.
