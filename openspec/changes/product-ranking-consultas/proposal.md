# Proposal — Product Ranking (Consultas)

Change: `product-ranking-consultas`
Project: `pricing-app`
Phase: propose
Status: draft

## Why / Intent

Comercial and product-management teams currently lack a single read-only view to assess the health of the catalog: which products are stale (not selling), how old the last purchase is, how much capital is tied up in stock at cost, and how much revenue that stock could generate at the classic sale price. Today this information is scattered across the ERP and multiple app tables (`productos_erp`, `tb_item_transactions`, `tb_item_storage`, `tb_price_list_items`, `marcas_pm`) with no consolidated, sortable analytics surface. This change introduces a new **Consultas** section whose first page is a **product ranking** that aggregates these signals into one filterable, sortable table. Success = a PM can open the page, filter by Marca/Categoría/PM and a warehouse selector, sort by any metric (ageing, last-purchase recency, stock value, potential revenue), and immediately identify slow-moving or capital-heavy products — all without write access and without inventing new ingestion pipelines.

## Scope

### In scope
- A new read-only backend router `consultas` exposing a paginated, dynamically-sorted product-ranking endpoint.
- Per-product columns: calculated ageing (days since last SALE), ERP ageing (from `scriptAgeing`), last purchase date + quantity, total stock valuation at cost (ARS), total potential revenue at classic sale price (ARS), plus PM / Marca / Categoría.
- Filters: Marca, Categoría, PM, and a **warehouse selector** (default `stor_id=1`, multi-depot selectable).
- Dynamic sorting on ANY exposed column via a whitelist (`SORT_COLUMNS`) pattern.
- A new permission namespace: `consultas.ver_ranking` (catalog seed + role mapping).
- A new frontend page under the existing routing/layout, with filter controls and a sortable table following the project design system, gated by the new permission.
- An Alembic migration to add storage for ERP ageing and a composite index on `tb_item_transactions` to support the last-sale and last-purchase lookups.
- A new ERP sync sub-deliverable for `scriptAgeing` — explicitly flagged as PENDING response-shape inspection at design time.

### Out of scope (explicit)
- **No materialized snapshot / pre-aggregated table at launch.** Ranking is computed live from existing data. (Noted as a future scale-out option below.)
- **No new sales-channel ingestion.** We reuse existing `tb_commercial_transactions` / `tb_item_transactions` data; we do NOT add ML / fuera-ML / TiendaNube ingestion pipelines.
- **No write operations** of any kind (read-only analytics page).
- **No changes to the existing pricing calculation engine** — we read the classic price (`prli_id=4`) and cost as-is.
- **No export/reporting features** (CSV/Excel) in this change — can be a follow-up.

## High-Level Approach

### Backend

**1. New `consultas` router + Pydantic v2 schemas.**
A new `backend/app/routers/consultas.py` with one ranking endpoint returning a paginated response model (rows + total count). Auth via `Depends(get_current_user)`, permission gated with `consultas.ver_ranking` using the existing `PermisosService` / `require_permiso` pattern. Schemas follow Pydantic v2 (`ConfigDict(from_attributes=True)`).

**2. Aggregation query strategy.**
A single aggregated `select()` over `productos_erp` as the base, with:
- LATERAL subquery for **last sale** (date, and the basis for calculated ageing) — filtered by the canonical "sale" definition (see open questions; `ct_kindOf` in `tb_commercial_transactions` discriminates sales across channels).
- LATERAL subquery for **last purchase** (`puco_id=10`, `MAX(it_cd)` + matching `it_qty`).
- JOIN to `tb_price_list_items` (`prli_id=4`) for classic price.
- LEFT JOIN to `marcas_pm` by `(marca, categoria)` text match, and onward to `Usuario.nombre` for PM filtering/display.
- Stock valuation from `tb_item_storage.itst_cant` summed over the **selected warehouses** (not the denormalized `productos_erp.stock`), multiplied by cost and by classic price.
- Cost normalized to ARS: `productos_erp.costo` + `moneda_costo`, converted via latest `TipoCambio.venta` (reuse the existing currency-conversion pattern in `pricing_calculator.py`).

Sorting and pagination applied at the DB level (`order_by` before `limit`/`offset`), driven by a `SORT_COLUMNS` whitelist modeled on `rrhh_empleados.py:464`. Because the existing `_paginate()` helper does not handle sorting, the ranking endpoint applies ordering explicitly.

**3. ERP ageing sync — FLAGGED sub-deliverable (PENDING `scriptAgeing` response-shape inspection at design time).**
`scriptAgeing` is registered in `gbp_parser.py:33` but never consumed, and there is a known discrepancy: the registered params say `["item_id"]` while old Streamlit code called it with `fromDate`/`toDate`. The response shape is UNKNOWN. We scope a new sync script + storage for ERP ageing here, but the concrete sync implementation MUST be deferred until the actual ERP script response is inspected during design. This sub-deliverable is independently shippable and should not block the calculated-ageing ranking.

**4. Migration (Alembic).**
- Add storage for ERP ageing (column on `productos_erp` vs separate table — decided in design; see open questions).
- Add a composite index on `tb_item_transactions` covering BOTH the purchase lookup (`item_id, puco_id, it_cd`) and the sales lookup. `puco_id` currently has no dedicated index, which is the main performance risk for the LATERAL subqueries.

**5. Permission seed.**
New `consultas.ver_ranking` permission in the `permisos` catalog + role mapping, following the established permission conventions.

### Frontend

- New page under the existing routing + `AppLayout`/Sidebar, added to `menuSections` with `permiso: 'consultas.ver_ranking'`.
- Filter controls: Marca, Categoría, PM, and a warehouse/depot selector (default depot 1, multi-select).
- A sortable table using the project's Tesla/table design system and design tokens, with server-side pagination (reuse `useServerPagination` and `useDebounce`), loading/error states, and `lucide-react` icons for sort indicators.
- Permission gating via `usePermisos()` (`tienePermiso('consultas.ver_ranking')`), plus `ProtectedRoute`. Backend remains the authoritative check.
- Light + dark mode support per design-system conventions.

## Open Questions for Design

1. **Canonical "sale" definition.** Which `ct_kindOf` values and which channels (ML, fuera-ML, TiendaNube) count as a "sale" for calculated ageing? This must be pinned down before the last-sale LATERAL is written.
2. **`scriptAgeing` response shape.** Real ERP response must be inspected; resolve the `item_id` vs `fromDate/toDate` param discrepancy. Determines whether ERP ageing is per-item days-of-stock or an accounting aging bucket.
3. **ERP ageing storage.** Column on `productos_erp` vs a separate ageing table — depends on the response shape (single scalar vs multi-bucket) and sync cadence.
4. **Index safety on a large table.** Confirm the composite index on `tb_item_transactions` is safe to create on a production-sized table (online/concurrent build, lock window, disk).
5. **Sales-velocity-over-window.** Is "days since last sale" sufficient, or is a sales-velocity-over-a-window metric (e.g., units sold in last N days) also required for the ageing signal?
6. **Currency display.** ARS-equivalent only, or original currency + ARS column for cost/valuation?

## Risks & Rollout

- **Performance (primary risk).** Live aggregation with two LATERAL subqueries over `tb_item_transactions` (potentially millions of rows) for thousands of products. Mitigation: the composite index (sales + purchase), DB-level pagination/sorting, and capping page size. If insufficient at scale, fall back to a materialized snapshot table refreshed on a schedule (explicit future option, out of scope for launch).
- **Unknown `scriptAgeing` contract.** Highest-uncertainty item. Mitigation: ERP ageing is an independent sub-deliverable, flagged PENDING; the ranking ships with calculated ageing even if ERP ageing slips.
- **Ambiguous sale definition.** Wrong `ct_kindOf` filtering would silently produce misleading ageing. Mitigation: pin the definition in design with explicit sign-off before implementation.
- **PM text join fragility.** The `(marca, categoria)` string join to `marcas_pm` has no FK; mismatched/whitespace text yields NULL PM. Mitigation: LEFT JOIN (never drops rows), surface unmatched as "sin PM".
- **Migration on large table.** Index creation lock window. Mitigation: validate concurrent-index strategy in design (question 4).
- **Rollout.** Ship behind the `consultas.ver_ranking` permission so the page is invisible until granted. Land the migration/index first, then the calculated-ageing ranking, then the ERP-ageing sync as a follow-up slice once the `scriptAgeing` shape is confirmed. Conventional commits; migrations via Alembic; Pydantic v2 throughout.
