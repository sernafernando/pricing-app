# SDD Tasks — product-ranking-consultas

**Delivery strategy**: ask-on-risk (see Review Workload Forecast at end)
**Strict TDD**: globally active; project has no test runner configured — see forecast.

---

## SLICE 1 — DB Groundwork [DONE]

### TASK-1.1 — [x] Migration M1: `productos_ageing` table + permission seed
**File**: `backend/alembic/versions/20260529_01_consultas_ageing_table_permiso.py`
**Depends on**: none
**What**:
- Create table `productos_ageing` (item_id INT PK FK→productos_erp.item_id, ageing_dias INT nullable, ageing_payload JSONB nullable, synced_at TIMESTAMP).
- INSERT INTO permisos (codigo=`consultas.ver_ranking`, categoria=`consultas`, es_critico=false) ON CONFLICT DO NOTHING.
- Assign permission to ADMIN rol (INSERT roles_permisos_base) ON CONFLICT DO NOTHING.
- Downgrade: clean roles_permisos_base, usuarios_permisos_override, permisos, DROP TABLE productos_ageing.
**Pattern**: follow `20260527_add_permiso_ver_prearmadas_stats.py` for permission seed; standard transactional migration for table creation.
**REQs**: REQ-06, REQ-09

### TASK-1.2 — [x] Migration M2: composite indexes (non-transactional)
**File**: `backend/alembic/versions/20260529_02_consultas_tit_indexes.py`
**Depends on**: TASK-1.1 (M2 must come after M1 in revision chain)
**What**:
- Non-transactional migration using `op.get_context().autocommit_block()`.
- `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_puco_cd ON tb_item_transactions (item_id, puco_id, it_cd DESC)` — purchase LATERAL perf.
- `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_cttx ON tb_item_transactions (item_id, ct_transaction)` — sale LATERAL perf.
- `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tct_sd_df_date ON tb_commercial_transactions (sd_id, df_id, ct_date)` — sale filter perf.
- Downgrade: `DROP INDEX CONCURRENTLY IF EXISTS` for each.
**Pattern**: follow `20260527_add_prearmados_armado_idx.py` precedent (autocommit_block).
**REQs**: REQ-10

---

## SLICE 2 — Backend Ranking Endpoint

### TASK-2.1 — SQLAlchemy model for `productos_ageing`
**File**: `backend/app/models/producto_ageing.py` (NEW)
**Depends on**: TASK-1.1
**What**:
- `ProductoAgeing` SQLAlchemy model mapping `productos_ageing` table.
- Columns: item_id (PK), ageing_dias (Integer nullable), ageing_payload (JSONB nullable), synced_at (DateTime nullable).
- FK relationship to `ProductoERP` (back_populates=`ageing`).
- Add `ageing` relationship on `ProductoERP` model (`backend/app/models/producto.py`, EDIT — add `uselist=False` backref).
**Pattern**: standard SQLAlchemy model per skill.
**REQs**: REQ-09

### TASK-2.2 — Pydantic v2 schemas for consultas
**File**: `backend/app/schemas/consultas.py` (NEW)
**Depends on**: none (can be parallel with TASK-2.1)
**What**:
- `RankingQueryParams`: Pydantic v2 model (or use FastAPI Query params directly on endpoint). Fields: marca (str|None), categoria (str|None), pm (str|None, "sin_pm" special value), stor_ids (list[int], default [1]), sort_by (str, default "dias_sin_venta"), sort_dir (Literal["asc","desc"], default "desc"), page (int ≥1, default 1), page_size (int ≥1 ≤200, default 50), ventana_dias (Literal[30,60,90,180], default 90), q (str|None).
- `RankingItemRow`: response row with all REQ-01 columns (item_id, codigo, descripcion, marca, categoria, pm, dias_sin_venta, erp_ageing, ultima_compra_fecha, ultima_compra_qty, stock_valuation_ars, potential_revenue_ars, total_stock, unidades_vendidas_ventana). All nullable except item_id/codigo/descripcion.
- `RankingResponse`: `{ items: list[RankingItemRow], total: int, page: int, page_size: int }`.
- All models use `model_config = ConfigDict(from_attributes=True)`.
**REQs**: REQ-01, REQ-04, REQ-05, REQ-07

### TASK-2.3 — Consultas router with ranking endpoint
**File**: `backend/app/routers/consultas.py` (NEW)
**Depends on**: TASK-2.1, TASK-2.2
**What**:
- `router = APIRouter(prefix="/api/consultas", tags=["consultas"])`.
- `GET /ranking` endpoint; `response_model=RankingResponse`.
- Permission gate: `require_permiso("consultas.ver_ranking")` dependency (reuse existing pattern from other routers).
- DB session via `get_db` (standard one-shot, NOT long-lived background session).
- **SORT_COLUMNS whitelist**: dict mapping key→labeled SQLAlchemy expression. Keys: `dias_sin_venta`, `ultima_compra_fecha`, `stock_valuation_ars`, `potential_revenue_ars`, `total_stock`, `codigo`, `descripcion`, `ultima_compra_qty`, `unidades_vendidas_ventana`. Unknown key → `raise HTTPException(422, detail=f"sort_by '{sort_by}' no válido")`.
- **Query structure**:
  - Base: `select(ProductoERP)` with `.where(ProductoERP.activo == True)` (unless `incluir_inactivos`).
  - Lateral #1 `last_sale`: over `tb_item_transactions ⋈ tb_commercial_transactions` WHERE `sd_id IN (1,4,21,56)` AND `df_id IN (all_channel_ids)` AND `it_qty != 0` AND `item_id = pe.item_id`; SELECT `MAX(ct_date) AS ultima_venta_fecha`, `SUM(it_qty) FILTER (WHERE ct_date >= now() - ventana_dias * interval '1 day') AS unidades_vendidas_ventana`.
  - Lateral #2 `last_purchase`: `tb_item_transactions` WHERE `puco_id = 10` AND `item_id = pe.item_id` ORDER BY `it_cd DESC` LIMIT 1; SELECT `it_cd AS ultima_compra_fecha`, `it_qty AS ultima_compra_qty`.
  - Stock subquery: `SUM(itst_cant) FROM tb_item_storage WHERE item_id = pe.item_id AND stor_id = ANY(:stor_ids)`.
  - `dias_sin_venta`: `EXTRACT(epoch FROM now() - ultima_venta_fecha) / 86400` CAST to int, NULL when ultima_venta_fecha IS NULL.
  - FX: one scalar `SELECT venta FROM tipo_cambio ORDER BY fecha DESC LIMIT 1`; multiply cost/price columns; NULL when no rate found.
  - JOIN `tb_price_list_items` WHERE `prli_id = 4` for precio_venta.
  - LEFT JOIN `marcas_pm` ON (marca, categoria) for pm.
  - LEFT JOIN `productos_ageing` for erp_ageing.
  - Filters: marca, categoria, pm (IS NULL when "sin_pm"), q ILIKE `%q%` on codigo|descripcion, stor_ids default [1].
  - `ORDER BY <whitelist_expr> <dir> NULLS LAST`.
  - Separate `SELECT COUNT(*)` over the same base+filters (no sort, no limit) for `total`.
  - `LIMIT page_size OFFSET (page-1)*page_size`.
- Docstring explaining sale definition constants.
**REQs**: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07

### TASK-2.4 — Register consultas router in main.py
**File**: `backend/app/main.py` (EDIT)
**Depends on**: TASK-2.3
**What**:
- `from app.routers import consultas`
- `app.include_router(consultas.router)`
**REQs**: REQ-01

---

## SLICE 3 — Frontend Page

### TASK-3.1 — Frontend API service for consultas
**File**: `frontend/src/services/consultasService.js` (NEW)
**Depends on**: TASK-2.3, TASK-2.4
**What**:
- `getRanking(params)` → `axios.get('/api/consultas/ranking', { params })`.
- Export typed param helper if needed.
- Follow existing `services/api.js` import pattern.
**REQs**: REQ-08

### TASK-3.2 — useConsultasRanking custom hook
**File**: `frontend/src/hooks/useConsultasRanking.js` (NEW)
**Depends on**: TASK-3.1
**What**:
- Wraps `useServerPagination` + `useDebounce` (reuse existing hooks).
- Accepts filter state, returns `{ rows, total, page, pageSize, loading, error, setPage, setPageSize, setSort }`.
- Debounce on text filter `q` (300ms).
**REQs**: REQ-08

### TASK-3.3 — RankingFilters component
**File**: `frontend/src/components/consultas/RankingFilters.jsx` (NEW)
**File**: `frontend/src/components/consultas/RankingFilters.module.css` (NEW)
**Depends on**: none (can be parallel with TASK-3.2)
**What**:
- Filter controls: Marca (select or text), Categoría (select or text), PM (select incl. "Sin PM"), Depósito (multi-select, default [1]).
- Uses Tesla Design System tokens (`--cf-*`) for light/dark.
- Emits `onFilterChange(filters)` callback.
- Empty/reset button.
**REQs**: REQ-03, REQ-08

### TASK-3.4 — RankingTable component
**File**: `frontend/src/components/consultas/RankingTable.jsx` (NEW)
**File**: `frontend/src/components/consultas/RankingTable.module.css` (NEW)
**Depends on**: TASK-3.2
**What**:
- Sortable table using `table-tesla.css` classes.
- Columns: Código, Descripción, Marca, Categoría, PM, Días sin venta, Ageing ERP, Última compra (fecha+qty), Stock total, Valorización ARS, Potencial ARS, Uds. vendidas (ventana).
- Sort icons via `lucide-react` (ChevronUp/ChevronDown/ChevronsUpDown).
- Click column header → call `setSort(col, dir)`.
- `erp_ageing` null → render "—".
- Loading state: skeleton rows or spinner.
- Empty state: "Sin resultados" message.
- Error state: error banner.
- Server-side pagination controls (prev/next, page indicator, page_size selector).
**REQs**: REQ-08, REQ-09

### TASK-3.5 — ConsultasRanking page
**File**: `frontend/src/pages/ConsultasRanking.jsx` (NEW)
**File**: `frontend/src/pages/ConsultasRanking.module.css` (NEW)
**Depends on**: TASK-3.3, TASK-3.4
**What**:
- Composes `RankingFilters` + `RankingTable` + `useConsultasRanking`.
- Wrapped in `AppLayout` (existing layout component).
- `ProtectedRoute` (or equivalent) guards direct URL access → 403 page if no `consultas.ver_ranking`.
- Page title: "Ranking de Productos".
**REQs**: REQ-06, REQ-08

### TASK-3.6 — Routing + Sidebar nav entry
**File**: `frontend/src/App.jsx` (or router config file, EDIT)
**File**: `frontend/src/components/layout/Sidebar.jsx` (EDIT)
**Depends on**: TASK-3.5
**What**:
- Add route `/consultas/ranking` → `<ConsultasRanking />` under the authenticated layout.
- Add Sidebar menu section "Consultas" (or append to existing if present) with entry "Ranking de Productos" gated by `consultas.ver_ranking` (hide if no permission, consistent with other permiso-gated entries).
**REQs**: REQ-06, REQ-08

---

## SLICE 4 — ERP Ageing Sync (Follow-up, gated)

> **STATUS: BLOCKED on live scriptAgeing inspection.** These tasks are INDEPENDENTLY SHIPPABLE after the field mapping is confirmed. Ranking works fully without them (LEFT JOIN tolerates empty `productos_ageing`).

### TASK-4.1 — sync_ageing.py sync script skeleton
**File**: `backend/app/scripts/sync_ageing.py` (NEW)
**Depends on**: TASK-1.1 (table exists), TASK-2.1 (model exists), **EXTERNAL: live scriptAgeing call to confirm field mapping**
**What**:
- Modeled on `sync_item_storage.py`.
- `_record_to_datos(raw)` function: maps scriptAgeing response fields → `{ ageing_dias: int, ageing_payload: dict }`. **Field keys TBD pending live call.**
- Main sync loop: call scriptAgeing endpoint, iterate results, `pg_insert(ProductoAgeing).on_conflict_do_update(...)`.
- BackgroundTasks pattern: opens its own DB session (follows `b20cec86` fix — does NOT leak pool connections).
- Placeholder constants for scriptAgeing URL + params (item_id vs fromDate/toDate TBD).
**REQs**: REQ-09

### TASK-4.2 — Cron/trigger wiring for sync_ageing
**File**: `backend/app/main.py` (EDIT) or scheduler config
**Depends on**: TASK-4.1
**What**:
- Register `sync_ageing` on startup event or existing scheduler (follow pattern of other sync scripts).
- Configurable interval via env var.
**REQs**: REQ-09

---

## Review Workload Forecast

| Dimension | Estimate |
|---|---|
| Slice 1 (migrations) | ~80 lines |
| Slice 2 (backend router + schemas + model) | ~300–350 lines |
| Slice 3 (frontend page + components + hook + service) | ~450–550 lines |
| Slice 4 (sync script skeleton) | ~100 lines |
| **Total (Slices 1–3)** | **~830–980 lines** |
| **Total (all slices)** | **~930–1080 lines** |

**400-line budget risk**: **HIGH** — total is 2–2.5× the 400-line soft limit.

**Chained/stacked PRs recommended**: **Yes**

**Natural PR boundaries**:
- **PR #1**: Slice 1 (migrations only) — low risk, reviewable independently, must land first.
- **PR #2**: Slice 2 (backend endpoint + schemas + model) — stacks on PR #1.
- **PR #3**: Slice 3 (frontend) — stacks on PR #2 (needs /api/consultas/ranking live).
- **PR #4**: Slice 4 (ageing sync) — independent follow-up, gated on live ERP call. No hard dependency on PR #3.

**Decision needed before apply**: **Yes** — delivery_strategy is `ask-on-risk`, so the orchestrator must confirm whether to proceed as chained PRs (recommended) or request `size:exception` for a single PR.

**Strict TDD note**: Project has "No tests configured" (no pytest, no vitest). However, Strict TDD is globally active. For apply:
- **Slice 2** (query logic, permission gating, sort whitelist, FX normalization) is the most testable — if a test runner is bootstrapped, unit tests for `SORT_COLUMNS` rejection and permission gate would be high value.
- **Slice 3** (React components) testable with vitest + React Testing Library if scaffolded.
- **Slices 1 and 4** (migrations, sync skeleton) are not unit-testable without an ERP fixture.
- **Recommendation**: Flag to user at apply time — apply agent should ask whether to bootstrap a minimal pytest config or proceed without tests (consistent with current project state).
