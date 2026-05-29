# Delta Spec — product-ranking-consultas

**Change**: product-ranking-consultas
**Phase**: spec
**Status**: approved
**Artifact store**: hybrid
**Created**: 2026-05-29

---

## Scope Summary

Read-only "Consultas" section with a product ranking page. No writes. No new ingestion pipelines. Gated behind a new permission `consultas.ver_ranking`. The ERP ageing sub-deliverable is OPTIONAL/PENDING and must NOT block the primary ranking functionality.

---

## REQ-01 — Ranking endpoint exists and returns paginated rows

**Requirement**: A `GET /api/consultas/ranking` endpoint must exist and return a paginated list of products, each row containing the following columns:

| Column | Description |
|--------|-------------|
| `item_id` | Internal product identifier |
| `codigo` | Product code |
| `descripcion` | Product description |
| `marca` | Brand name |
| `categoria` | Category name |
| `pm` | PM name (nullable — "sin PM" when null) |
| `calculated_ageing_days` | Days since last SALE (integer, nullable when no sales exist) |
| `erp_ageing` | ERP ageing value from scriptAgeing sync (nullable — always nullable at launch, see REQ-09) |
| `last_purchase_date` | Date of last purchase (nullable) |
| `last_purchase_qty` | Quantity of last purchase (nullable) |
| `stock_valuation_ars` | Stock quantity for selected depot(s) × cost in ARS (nullable when cost unavailable) |
| `potential_revenue_ars` | Stock quantity for selected depot(s) × classic price in ARS (nullable when price unavailable) |
| `total_stock` | Total stock units across selected depot(s) |

**Acceptance scenarios**:

- **Given** an authenticated user with `consultas.ver_ranking`, **when** `GET /api/consultas/ranking` is called with no extra params, **then** the response is HTTP 200 with a body matching `{ items: [...], total: int, page: int, page_size: int }`.
- **Given** a product that has no recorded sales, **when** it appears in ranking results, **then** `calculated_ageing_days` is `null` (not zero, not absent).
- **Given** a product whose cost is in a foreign currency, **when** it appears in ranking results, **then** `stock_valuation_ars` uses the latest `TipoCambio.venta` rate to normalize to ARS.
- **Given** a product with no entry in `tb_price_list_items` for `prli_id=4`, **when** it appears in results, **then** `potential_revenue_ars` is `null`.
- **Given** a product with no PM mapping in `marcas_pm`, **when** it appears in results, **then** `pm` is `null` (the row is still returned — not filtered out).

---

## REQ-02 — Calculated ageing is based on last SALE, not last purchase

**Requirement**: `calculated_ageing_days` MUST reflect the number of days elapsed since the product's most recent sale transaction. The canonical sale definition — which values of `ct_kindOf` and which channels (ML, non-ML, TiendaNube, etc.) constitute a "sale" — is an open design question. This spec requires the implementation to honor whatever canonical sale definition the design phase pins, not a hardcoded assumption.

**Acceptance scenarios**:

- **Given** the canonical sale definition is resolved in design, **when** the ranking query executes, **then** `calculated_ageing_days` counts days since the latest transaction matching that definition.
- **Given** a product that has purchases but zero sales matching the canonical definition, **when** it appears in ranking results, **then** `calculated_ageing_days` is `null`.
- **Given** the canonical sale definition is a design dependency, **when** specs are written, **then** no implementation may hardcode `ct_kindOf` values without design sign-off.

---

## REQ-03 — Filters: Marca, Categoría, PM, and warehouse selector

**Requirement**: The endpoint must accept the following optional query parameters for filtering:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `marca` | string | none (all) | Filter by exact brand name |
| `categoria` | string | none (all) | Filter by exact category name |
| `pm` | string | none (all) | Filter by PM name; special value `"sin_pm"` returns rows where PM is null |
| `stor_ids` | list[int] | `[1]` | Depot IDs for stock aggregation; supports multi-depot |

**Acceptance scenarios**:

- **Given** `marca=Lenovo` is passed, **when** the query runs, **then** only rows with `marca="Lenovo"` are returned.
- **Given** `pm=sin_pm` is passed, **when** the query runs, **then** only rows where the PM LEFT JOIN returned null are returned.
- **Given** no `stor_ids` is passed, **when** the query runs, **then** stock is aggregated over `stor_id=1` only (default).
- **Given** `stor_ids=[1,3]` is passed, **when** the query runs, **then** stock is aggregated over depots 1 and 3 combined.
- **Given** all filter params are omitted, **when** the query runs, **then** the full catalog is returned (subject to pagination).

---

## REQ-04 — Dynamic sorting on any exposed column

**Requirement**: The endpoint must accept `sort_by` (column key) and `sort_dir` (`asc` | `desc`) query parameters. Sorting must happen at the database level, before pagination is applied. Only columns in a server-side `SORT_COLUMNS` whitelist are valid sort keys. Unknown keys must be rejected.

**Acceptance scenarios**:

- **Given** `sort_by=calculated_ageing_days&sort_dir=desc`, **when** the query runs, **then** rows are ordered from highest ageing to lowest.
- **Given** `sort_by=stock_valuation_ars&sort_dir=asc`, **when** the query runs, **then** rows are ordered from lowest to highest valuation.
- **Given** `sort_by=unknown_column`, **when** the request is received, **then** the server returns HTTP 422 with an error identifying the invalid sort key.
- **Given** `sort_dir=lateral` (invalid direction), **when** the request is received, **then** the server returns HTTP 422.
- **Given** no `sort_by` is passed, **when** the query runs, **then** the server applies a stable default sort (design decides the default; spec only requires it be deterministic).
- **Given** sorting on a nullable column (e.g., `calculated_ageing_days`) with `sort_dir=desc`, **when** the query runs, **then** null values appear last (NULLS LAST semantics).

---

## REQ-05 — Pagination behavior

**Requirement**: The endpoint must accept `page` (1-based) and `page_size` query parameters. Both must be validated and bounded.

| Parameter | Default | Min | Max |
|-----------|---------|-----|-----|
| `page` | 1 | 1 | unbounded |
| `page_size` | 50 | 1 | 200 |

The response body must include `total` (total matching rows), `page`, and `page_size` in addition to the `items` array.

**Acceptance scenarios**:

- **Given** 150 total rows match the current filters, **when** `page=2&page_size=50` is requested, **then** rows 51–100 are returned and `total=150`.
- **Given** `page_size=0` is passed, **when** the request is received, **then** HTTP 422 is returned.
- **Given** `page_size=500` is passed, **when** the request is received, **then** HTTP 422 is returned (exceeds max).
- **Given** `page=99` on a result set smaller than 99 pages, **when** the request is received, **then** `items` is an empty list and `total` reflects the real count.

---

## REQ-06 — Permission gating: `consultas.ver_ranking`

**Requirement**: Access to `GET /api/consultas/ranking` requires the authenticated user to hold the permission `consultas.ver_ranking`. The permission must be seeded in the `permisos` table via Alembic migration and mappable to roles via `rol_permiso_base`. SUPERADMIN always passes.

**Acceptance scenarios**:

- **Given** an unauthenticated request (no JWT), **when** the endpoint is called, **then** HTTP 401 is returned.
- **Given** a valid JWT for a user without `consultas.ver_ranking`, **when** the endpoint is called, **then** HTTP 403 is returned.
- **Given** a valid JWT for a user with `consultas.ver_ranking`, **when** the endpoint is called with valid params, **then** HTTP 200 is returned.
- **Given** a SUPERADMIN user, **when** the endpoint is called, **then** HTTP 200 is returned regardless of explicit permission assignment.
- **Given** the permission `consultas.ver_ranking` does not yet exist in the `permisos` table, **when** the Alembic migration runs, **then** it is inserted exactly once (idempotent seed).

---

## REQ-07 — Currency normalization to ARS

**Requirement**: `stock_valuation_ars` and `potential_revenue_ars` must always be expressed in ARS. Products whose cost or price is stored in a foreign currency must be converted using the latest available `TipoCambio.venta` rate for that currency. The conversion pattern must reuse the existing `pricing_calculator` pattern in the codebase — no new conversion logic.

**Acceptance scenarios**:

- **Given** a product with `moneda_costo = "USD"` and `TipoCambio.venta = 1000`, **when** its ranking row is returned, **then** `stock_valuation_ars = stock_qty × cost_usd × 1000`.
- **Given** a product with `moneda_costo = "ARS"`, **when** its ranking row is returned, **then** `stock_valuation_ars = stock_qty × cost_ars` (no FX multiplication).
- **Given** no `TipoCambio` record exists for the product's currency, **when** its ranking row is returned, **then** `stock_valuation_ars` is `null` (not zero, not an error).

---

## REQ-08 — Frontend page: filters, sortable table, states, theming

**Requirement**: A new frontend page must be created at a route under the "Consultas" section. The page must:

1. Render filter controls for Marca, Categoría, PM, and depot selector.
2. Render a sortable data table using `table-tesla.css` with all columns from REQ-01.
3. Show column sort indicators (lucide-react icons) for the currently active sort column and direction.
4. Support server-side pagination using `useServerPagination` and `useDebounce`.
5. Show distinct loading, error, and empty-state UI feedback.
6. Work correctly in both light and dark mode using `--cf-*` design tokens.
7. Be hidden from the Sidebar navigation when the user lacks `consultas.ver_ranking`.
8. Be wrapped in `ProtectedRoute` so direct URL access also enforces the permission.

**Acceptance scenarios**:

- **Given** the user selects `marca=Lenovo` in the filter, **when** the debounce delay elapses, **then** a new API request is fired with `marca=Lenovo` and results update.
- **Given** the user clicks a sortable column header, **when** the click is processed, **then** the sort icon updates and a new API request is fired with the updated `sort_by` and `sort_dir`.
- **Given** the API call is in-flight, **when** the table is rendered, **then** a loading indicator is visible and the table rows are not shown.
- **Given** the API returns an error, **when** the component renders, **then** a user-visible error message is shown (not a blank page).
- **Given** filters produce zero results, **when** the component renders, **then** an explicit empty-state message is shown.
- **Given** the user does not have `consultas.ver_ranking`, **when** the Sidebar renders, **then** no "Consultas" section or ranking link is visible.
- **Given** the user navigates directly to the ranking URL without the permission, **when** the route renders, **then** they are redirected or see a 403/access-denied view.
- **Given** the user toggles between light and dark mode, **when** the page renders in each mode, **then** text contrast meets WCAG AA and no hardcoded colors appear.

---

## REQ-09 — ERP ageing is OPTIONAL/PENDING and must not block the ranking

**Requirement**: The `erp_ageing` column is an optional enrichment field sourced from the `scriptAgeing` ERP sync. The ranking endpoint and page MUST function correctly when `erp_ageing` is null for all rows. The scriptAgeing sync sub-deliverable — including the ERP response shape, the `item_id` vs `fromDate/toDate` parameter discrepancy, and the Alembic migration for storing ageing data — is PENDING design resolution and is independently shippable after the calculated-ageing ranking is live.

**Acceptance scenarios**:

- **Given** `erp_ageing` is null for every row, **when** the ranking is requested, **then** HTTP 200 is returned with all other columns populated as normal.
- **Given** `erp_ageing` is null for a row, **when** the row is rendered in the frontend table, **then** the cell shows a dash or "—" placeholder (not an error, not blank space that breaks layout).
- **Given** the scriptAgeing sync has not yet been implemented, **when** the ranking endpoint is deployed, **then** no runtime error is raised due to missing ERP ageing data.
- **Given** the ERP ageing design question is unresolved (response shape unknown), **when** this spec is written, **then** no column definition, storage schema, or sync shape is mandated here — those are design-phase outputs.

---

## REQ-10 — Composite index on `tb_item_transactions` must exist before ranking goes live

**Requirement**: Before the ranking endpoint is deployed to production, an Alembic migration must create at minimum a composite index on `tb_item_transactions` covering the purchase lookup (`item_id`, `puco_id`, `it_cd`). An analogous index for the sales lookup is also required. Both indexes must be created using `CONCURRENTLY` (or the Alembic equivalent) to avoid table-level lock during deployment.

**Acceptance scenarios**:

- **Given** the migration runs on a populated database, **when** it completes, **then** both composite indexes exist and no full table scan is required for the ranking query's purchase and sale LATERAL subqueries.
- **Given** the index creation uses `CONCURRENTLY`, **when** the migration runs, **then** no exclusive lock is held on `tb_item_transactions` for more than a brief moment (design decides exact approach).

---

## Design Dependencies (open questions that spec does NOT resolve)

These items are flagged as requiring design-phase answers before implementation. Requirements above reference them explicitly.

| ID | Question | Impacts |
|----|----------|---------|
| D-1 | Canonical sale definition: which `ct_kindOf` values and channels count as a sale? | REQ-01, REQ-02 |
| D-2 | scriptAgeing response shape and parameter contract (`item_id` vs `fromDate/toDate`) | REQ-09 |
| D-3 | ERP ageing storage: column on `productos_erp` vs separate table | REQ-09 |
| D-4 | Default sort column for ranking when no `sort_by` is passed | REQ-04 |
| D-5 | Currency display preference: ARS-only vs original + ARS column | REQ-01, REQ-07 |
| D-6 | Index creation strategy for large `tb_item_transactions` (lock window, concurrent build) | REQ-10 |

---

## Out of Scope (explicit)

- Materialized snapshot / caching layer (future scale-out only)
- New sales-channel ingestion
- Any write operations
- Pricing engine changes
- Export / CSV download
- Sales velocity over a rolling window (beyond last-sale date)
