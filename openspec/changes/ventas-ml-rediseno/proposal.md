# Proposal: Ventas ML redesign (listing + fixed detail panel + KPI strip + authoritative stored Total Gauss)
Revision 2 (supersedes rev 1). Skills read: pricing-app-backend, -frontend, -design, -pricing-logic.

## Intent
Rebuild the Ventas ML screen (frontend/src/pages/VentasML.jsx + DesgloseDrawer.jsx) following docs/design/ventas-ml/{listado,detalle}.{html,jpg}: denser data, lucide icons per concept, monospace figures, card sections. Problems: (1) detail is a modal that blocks selecting/copying row data; (2) persisted data (city, shipment substatus, ML coupon, buyer real name, payment method/installments, IVA non-reconcile reasons) is never shown; (3) no aggregate view of the filtered set, which is the base for future metrics; (4) no search; (5) per-order Total Gauss/neto/markup are recomputed live on every read (deducciones.calcular_total_gauss) while the stored total_gauss column is only a sort key that can be stale -- aggregates cannot be trusted. The user's rule: the STORED value is the source of truth and must always be up to date, because we know every event that changes its inputs.

## Binding user decisions
1. Placeholder/category thumbnail only; no /items calls.
2. Detail = FIXED side panel next to the table (wide monitors), non-modal; closes when no row is selected; rows stay selectable/copyable.
3. KPI strip aggregates the FULL FILTERED SET via a backend aggregation.
4. APIs may ship ahead of the UI as long as nothing breaks (BE-first slicing stands).
5. Stored per-order Total Gauss is authoritative, recomputed transactionally on every input-changing event; no on-the-fly or frontend computation of metrics. Live-recompute readers switch to reading stored values.
6. Doubtful cases: ONE on/off TOGGLE SWITCH each (switch UI, not checkboxes) deciding whether they count in the KPI strip: status `unknown` ("A revisar", VentasML.jsx:78,99), pack `mixed` ("Mixta"), `in_dispute` ("En disputa"), Total Gauss `provisional` ("Provisorio"). KPI endpoint receives them as explicit params; the shared filter builder applies them identically to listing and KPI.
7. Search bar IN scope.
8. No invented data; lucide icons; design tokens only; light + dark.

## Defaults set by orchestrator (still flagged for user review)
- D1 Drop Stitch-invented data: trends vs previous month, "Objetivo 25%", card brand/last-4, CUIT, invoice type/download, account selector, new top nav, bell, "Sincronizado hace X".
- D2 Buyer: nickname + real name only if present in raw_order.buyer; city/province from MlShipmentOps.receiver_address.
- D3 "Resincronizar" = re-fetch order + payments via existing ingestion paths (and, by decision 5, that path recomputes stored Gauss).
- D4 lucide-react, tokens only, existing --font-mono.
- D5 Show IVA `razones` instead of bare "no reconcilia".

## Deferred by agent -- PENDING USER OK (not user-decided)
CSV export, column chooser, estimated delivery date, "Recalcular Costo Gauss" button (partly subsumed by decision 5), loading JetBrains Mono webfont (use token fallback stack).

## Scope
### In
A. Authoritative stored metrics (new, precedes KPI):
- Decide in design which per-order values are stored (minimum: total_gauss, provisional flag + provisional_falta, markup; likely neto and neto_sin_iva too, since Gauss depends on them and KPI sums neto). Stored state is explicit: value + status (ok / provisional / unresolved) -- never a silently wrong number; unresolved stays NULL with a status, not 0.
- ONE recompute entry point reusing calcular_total_gauss (bulk, no per-order query loop), invoked in the SAME transaction as every input write. Design must enumerate every write path with codegraph; candidates known today: payment ingestion + sweep, deferred payments recheck, refunds (incl. repair-refunds script), frozen cost writes (ml_order_item_costos, backfill_costo_congelado), Flex shipping cost resolution (resolve_flex_cost_by_order_ids inputs, marcar_stale), "% de varios" config change (fan-out recompute over affected orders), backfill_payments_costs_service, link_resolver/divergence services, repair/backfill scripts, per-order resync. A missed trigger = silent wrong metric, so the enumeration is a design deliverable with a test per trigger.
- One-time backfill script (batched, pool-safe via get_background_db short-lived blocks) + divergence check (stored vs recomputed; script and/or metric) run and clean BEFORE readers switch.
- Switch readers (listing, detail, KPI) to stored values. Detail still shows the chain breakdown, but its total MUST equal the stored total (invariant test).
B. Listing restyle: Producto column (placeholder + title + SKU + MLA + qty), stacked operation/goods badges, envio mode + substatus, importe + coupon, neto/Total Gauss/markup mono, unified alert level derived server-side, facet chips with counts, pack sub-rows restyled, SEARCH bar (server-side, through the shared filter builder; fields proposed: order id, pack id, MLA, SKU, title, buyer nickname -- final field list for design).
C. Fixed side detail panel replacing the modal: Producto, Comprador, Envio, Pago (method/installments/approval/paid/coupon), neto waterfall + IVA per rate (+razones), Total Gauss chain + markup (stored total), actions "Ver en ML" and "Resincronizar".
D. Backend additive optional fields on sales list + breakdown endpoints; nothing removed or renamed.
E. Shared filter builder (listing + KPI + search + doubtful toggles) and KPI endpoint: count, gross billed, neto ML, Total Gauss (SUM of stored), average markup, counts per doubtful class (so the UI can say how many were excluded).
F. KPI strip with four doubtful-class toggle switches.
G. Per-order resync endpoint (permission-gated) delegating to ingestion.

### Out
Real thumbnails; CUIT, card digits, invoices; trends/targets; account switcher/top nav; the pending-OK deferred list above; any change to the breakdown MATH itself (we move where it is persisted/read, not the formula).

## Open questions (return to orchestrator; do not assume)
- Q1 Do the four doubtful toggles also filter the TABLE, or only the KPI strip? Proposal: toggles affect KPI only by default; table already has status/pack facets. Needs user decision -- blocks KPI/FE spec detail only.
- Q2 Default toggle states (proposal: unknown OFF, mixed ON, in_dispute OFF, provisional ON with a "Provisorio" count shown). Needs user decision.
- Q3 Should toggle state persist (URL param vs localStorage vs none)? Proposal: URL params, same as other filters.

## Capabilities
### New
- `ml-order-stored-metrics`: authoritative per-order stored neto/neto_sin_iva/Total Gauss/markup + status; recompute-on-write contract per trigger; backfill; divergence check; readers use stored values; detail-total == stored invariant.
- `ml-sales-kpi-aggregation`: KPI over the full filtered set via shared filter builder; doubtful-class toggle params; excluded-count reporting; parity with listing.
- `ml-sales-detail-panel`: fixed side panel behavior, sections, actions, copyable data.
- `ml-order-resync`: single-order re-fetch via existing ingestion, permission + error semantics, triggers recompute.
- `ml-sales-search`: server-side search through the shared filter builder.
### Modified
- `ml-sales-listing`: new columns, alert level, additive fields, chips, stored-value reads, search.
- `ml-order-breakdown`: additive buyer/shipment/payment fields; IVA razones; total sourced from stored value.

## Approach
Recommended: stored-metrics-first, then additive incremental UI. Rejected: (a) SUM of a possibly-stale column + staleness counter, and (b) live batch recompute with a cap -- both violate decision 5. Recompute uses the existing single producer (calcular_total_gauss) so there is one formula; persistence is in the caller's transaction (memory rule: any price/amount write must recompute dependent stored columns in the same transaction). "% de varios" changes fan out as a batched background recompute with a divergence re-check; design to decide whether that is in-transaction or a tracked job with explicit "recomputing" status (flag). Readers switch only after backfill + zero divergence. Frontend never computes metrics. Detail panel: CSS grid listing|panel, selection in URL param, non-modal (no focus trap), Escape clears selection, collapses below a breakpoint.

## Rough PR slicing (~400 changed lines each, each safe alone; auto-chain)
1. BE: stored-metrics schema (Alembic YYYYMMDD migration with downgrade; columns nullable + status) + single recompute service + tests. No readers changed.
2. BE: wire recompute into ingestion/sweep/recheck/refunds triggers + per-trigger tests. (May split 2a/2b.)
3. BE: wire cost writes, Flex resolution, varios fan-out, repair/backfill scripts + tests.
4. BE: backfill script + divergence check script/metric; run in prod, verify zero divergence (gate).
5. BE: readers (listing, detail, KPI-ready) read stored values; detail-total invariant test.
6. BE: additive listing fields (city/province, substatus, coupon, alert level) + shared filter builder + search param.
7. FE: listing restyle + search bar; VentasML tests evolved.
8. BE: additive breakdown fields (buyer real name, payment method/installments, shipment).
9. FE: fixed side panel (may split 9a shell/existing sections, 9b new sections); Desglose tests migrated.
10. BE: KPI endpoint with doubtful-class params + excluded counts + parity tests.
11. FE: KPI strip + four toggle switches.
12. BE+FE: resync endpoint + panel button.
PRs 6-9 are independent of 1-5 and may proceed in parallel chains; 10 depends on 5.

## Affected areas
| Area | Impact | Description |
|---|---|---|
| backend/app/models/ml_orders_ops.py + alembic/versions | Modified/New | stored metric columns + status |
| backend/app/services/ml_ventas_desglose/deducciones.py, breakdown_service.py | Modified | single recompute/persist entry (persistir_total_gauss, marcar_stale exist today) |
| backend/app/services/ml_orders_ingestion/* (ingestion, backfill_payments_costs, link_resolver, divergence) | Modified | recompute triggers |
| payments recheck, refunds repair, backfill_costo_congelado, Flex cost resolution, varios config writer | Modified | recompute triggers (full list = design) |
| backend/app/routers/ml_ventas_ops.py | Modified | shared filter builder, search, stored reads, KPI, resync |
| backend/app/scripts/ (new) | New | backfill + divergence check |
| frontend/src/pages/VentasML.jsx (+test, css module) | Modified | listing, search, KPI strip, toggles |
| frontend/src/components/DesgloseDrawer.jsx (+test) | Modified | becomes fixed panel |
| backend/tests/integration/test_ml_ventas_ops_{sales_router,router}.py, tests/services/ml_ventas_desglose | Modified | parity/invariant/trigger tests |

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Missed write trigger -> stored metric silently wrong | High | codegraph-enumerated trigger list in design, one test per trigger, divergence check as recurring metric |
| Backfill load / DB pool exhaustion (2026-06-24 incident) | Med | batched, short-lived get_background_db blocks, off-hours |
| "% de varios" fan-out over many orders in one txn | Med | batched job with explicit recomputing status; design decides |
| KPI diverges from listing | Med | shared filter builder, parity tests list-sum vs KPI incl. toggles |
| Detail total != stored | Med | invariant test |
| Coverage lost in modal->panel migration | Med | assertion mapping per PR |
| raw_payload/receiver_address JSONB shape varies | Med | captured fixtures only, null-safe |
| Resync abuse/rate limits | Med | permission gate, single order, fail-closed |
| Search query cost | Low-Med | indexed columns; EXPLAIN in design |
| ruff format / LF gotchas | Low | ruff format app/ tests/ alembic/ before push |

## Rollback Plan
UI/additive PRs revert independently. Stored-metrics: migration ships downgrade; columns stay non-authoritative (readers unchanged) until PR4 divergence gate passes, so reverting PR5 restores live-recompute readers without data loss; trigger PRs revert to prior writes (column just goes stale, not read). KPI/resync/search are new routes/params -- revert removes them.

## Dependencies
- Design: full write-path enumeration + which values are stored + varios fan-out strategy (blocks PR1-5).
- User answers Q1-Q3 (block KPI/toggle spec detail only; PR1-9 proceed).
- Confirm single-order ingestion fetch is reusable (blocks PR12 only).

## Success Criteria
- [ ] Stored Total Gauss/markup (+status) match a fresh recompute for 100% of orders after backfill (divergence check = 0) and stay at 0 across a monitoring window.
- [ ] Every enumerated trigger has a test proving recompute in the same transaction.
- [ ] Listing, detail, KPI read stored values; no live recompute on read; detail chain total == stored total (tested).
- [ ] Provisional/unresolved are explicit stored states, never a fabricated number.
- [ ] KPI equals aggregate of the full filtered set incl. toggle combinations (parity tests); excluded counts shown.
- [ ] Four doubtful toggles are switch controls, passed as explicit params, applied identically by the shared filter builder.
- [ ] Search works server-side through the shared builder.
- [ ] Fixed side panel; rows copyable while open; closes on deselect.
- [ ] No invented data; placeholder thumbnail; lucide; tokens; light + dark pass.
- [ ] Test count >= baseline (183) with mapped replacements; strict TDD RED-first; each PR <= ~400 lines and mergeable alone.

## Diff vs rev 1
- Removed KPI options (a) stale SUM + counter and (b) capped live recompute; adopted (c) stored-authoritative as mandatory, new capability ml-order-stored-metrics, new PR1-5 sequence before KPI.
- Readers switch to stored values (was: live recompute kept).
- Added four doubtful-class toggle switches + explicit KPI params + excluded counts; open Q1-Q3.
- Search bar moved IN scope (new capability ml-sales-search).
- Remaining self-deferred items relabeled "deferred by agent, pending user OK".
- Re-sliced from 7 to 12 PRs; rollback, risks, success criteria updated.

## Status: PAUSED
This change is paused. It depends on `ml-ventas-neto-iibb-varios` merging and deploying first (that change corrects the underlying Total Gauss/neto formula; freezing the OLD formula into this change's stored-metrics table would be far costlier to fix later). See design.md's appended "Pending requirement from ml-ventas-neto-iibb-varios" section.
