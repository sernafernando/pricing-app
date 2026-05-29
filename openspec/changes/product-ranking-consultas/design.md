# Design — product-ranking-consultas

> SDD design phase. Artifact store: hybrid (also in engram `sdd/product-ranking-consultas/design`).
> Honors LOCKED decisions from `sdd/product-ranking-consultas/decisions` (#448) and the proposal (#449).
> This is the architectural HOW. No task breakdown here.

---

## 1. Architecture overview

Read-only "Consultas" section. First page = product ranking. One consolidated, sortable,
server-paginated view over `productos_erp` enriched with last-sale, last-purchase, stock
valuation and classic price, gated by a new `consultas.ver_ranking` permission.

Layering (matches existing project conventions):

```
frontend/src/pages/ConsultasRanking.jsx        ← page (filters + table)
frontend/src/components/consultas/*            ← presentational sub-components
frontend/src/hooks/useServerPagination.js      ← REUSE (already exists)
frontend/src/hooks/useDebounce.js              ← REUSE (already exists)
        │  axios services/api.js
        ▼
backend/app/routers/consultas.py               ← NEW router, prefix /api, gated
backend/app/schemas/consultas.py (or inline)   ← NEW Pydantic v2 schemas
        │
        ▼
single SQLAlchemy select() over productos_erp + 2 LATERAL + JOINs   ← core aggregation
        │
        ▼
PostgreSQL  (productos_erp, tb_item_transactions, tb_commercial_transactions,
             tb_item_storage, tb_price_list_items, marcas_pm, usuarios, tipo_cambio)
```

Separate, independently-shippable sub-deliverable:

```
backend/app/scripts/sync_ageing.py             ← NEW sync (scriptAgeing) — FLAGGED PENDING shape
backend/app/models/producto_ageing.py          ← NEW model (storage decision below)
alembic migration                              ← ERP-ageing storage + composite index
```

Design principle honored: **no materialized snapshot at launch**. The ranking is computed live
with DB-level filter → sort → paginate. Materialized snapshot is the documented scale-out fallback.

---

## 2. Canonical "sale" definition — RESOLVED

Investigated `ventas_fuera_ml.py`, `ventas_tienda_nube.py`, `ventas_ml.py`,
`commercial_transactions.py`, and the `agregar_metricas_*` scripts.

**Finding.** All non-ML sales in this codebase are identified at the
`tb_item_transactions tit` ⋈ `tb_commercial_transactions tct` level using two discriminators:

- `tct.sd_id` — sales document sign:
  - `SD_VENTAS = [1, 4, 21, 56]` → venta (+1)
  - `SD_DEVOLUCIONES = [3, 6, 23, 66]` → nota de crédito / devolución (−1)
- `tct.df_id` — document file (channel/fiscal type):
  - fuera-ML: explicit allowlist `DF_PERMITIDOS` (facturas/NC/ND, excludes remitos 107/110, recibos 112)
  - TiendaNube: `df_id IN (113, 114)`
  - MercadoLibre: `df_id IN (129, 130, 131, 132)` (excluded from fuera-ML, has its own MLO pipeline)

The channel split is purely a `df_id` partition over the SAME transaction tables. ML orders are
*also* present in `tb_item_transactions` (df_id 129-132); the separate `tmlod`/MLO pipeline exists
for commission/shipping detail, NOT because ML sales live in a different table.

**Decision for "last sale" (channel-unified).** For ageing we want "the last time this item
actually went out the door as a sale, on any channel." Therefore:

```sql
-- "is a sale movement" predicate, channel-agnostic:
tit.item_id = :item_id
AND tct.sd_id IN (1, 4, 21, 56)          -- VENTAS only (NOT returns) for "last sale date"
AND tct.df_id IN (<DF_VENTA_TODOS>)      -- union: DF_PERMITIDOS ∪ {113,114} ∪ {129,130,131,132}
AND tit.it_qty <> 0
AND (tit.item_id NOT IN (16, 460))       -- existing excluded pseudo-items
```

Rationale:
- `sd_id IN SD_VENTAS` only (exclude `SD_DEVOLUCIONES`) — ageing asks "when did we last SELL it";
  a return is the opposite of a sale and must not reset the ageing clock.
- Union ALL channel `df_id`s — a PM cares whether the product moves *anywhere*, not per-channel.
  A product selling only on ML is not stale.
- Reuse the same item/cliente exclusions already battle-tested in `ventas_fuera_ml.py`
  (items 16, 460 = "Envío"/pseudo). Customer/vendor exclusions are NOT applied here: those filter
  internal/test operations for revenue reporting, but for "did it sell at all" we keep it simple
  and avoid the dynamic `VendedorExcluido` lookup inside a per-row LATERAL.

**Constants.** Centralize in `consultas.py` (do not import the channel modules to avoid coupling):

```python
SD_VENTAS = [1, 4, 21, 56]
DF_VENTA_TODOS = sorted(set(DF_PERMITIDOS) | {113, 114} | {129, 130, 131, 132})
ITEMS_EXCLUIDOS = [16, 460]
```
where `DF_PERMITIDOS` is copied (with a comment pointing to `ventas_fuera_ml.py` as the source of truth).

**Confidence: HIGH.** This is defensible and matches existing revenue logic. The one judgment call
(ventas-only, channel-union, no vendor/customer exclusion) is documented above. Flag for a one-line
user confirmation at apply time, but do NOT block design on it.

---

## 3. Sales velocity over window — RESOLVED

User definition: ageing = "tiempo que no se vendió O si hay poca venta en X tiempo."

**Decision: expose BOTH** in the ranking row, computed in the same last-sale LATERAL pass is not
possible (different aggregation), so use a second small correlated aggregate:

- `dias_sin_venta` — `(NOW()::date - last_sale_date::date)` from the last-sale LATERAL (primary ageing).
- `unidades_vendidas_ventana` — `SUM(it_qty)` of sale movements within the last `N` days.

`N` is a **query parameter `ventana_dias` (default 90, allowed {30, 60, 90, 180})**. Default 90 is
the standard "slow mover" horizon; configurable so PMs can tighten/loosen. Both columns are sortable.
This satisfies "poca venta en X tiempo" without committing to a velocity score formula now
(a derived score is a future enhancement, out of scope).

**Confidence: HIGH.**

---

## 4. ERP ageing storage — RESOLVED (storage) / field-mapping PENDING

`scriptAgeing` is registered (`gbp_parser.py:33`, params `["item_id"]`) but never consumed; its
response shape is UNKNOWN. We must design storage that tolerates EITHER a scalar OR multi-bucket
response without a future migration.

**Decision: separate table `productos_ageing` (NOT a column on `productos_erp`).** Rationale:
- `productos_erp` is sync-managed by `erp_sync` with a `hash_datos` change-detection — adding an
  ageing column owned by a *different* sync cadence would muddy that hash and risk false "changed"
  detections. Keep ERP master data and ERP-ageing in separate lifecycles.
- A separate table absorbs an unknown shape: one row per item with a flexible payload.
- One-to-one with `productos_erp.item_id`; LEFT JOIN in the ranking (item may have no ageing yet).

```python
# backend/app/models/producto_ageing.py
class ProductoAgeing(Base):
    __tablename__ = "productos_ageing"
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), primary_key=True)
    # Scalar interpretation (if scriptAgeing returns a single number of days):
    ageing_dias = Column(Integer, nullable=True)
    # Multi-bucket / arbitrary interpretation (if it returns brackets/qty-by-bucket):
    ageing_payload = Column(JSONB, nullable=True)   # raw ERP buckets, future-proof
    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

The ranking exposes `ageing_erp_dias` (= `ageing_dias` when scalar) and passes through
`ageing_erp_payload` for the FE to render buckets if present. The sync writes whichever field(s)
the real response populates.

**Sync script** `sync_ageing.py` modeled on `sync_item_storage.py`:
- `requests.get(WORKER_URL, params={"strScriptLabel": "scriptAgeing", "itemID": item_id})`
- bulk upsert with `pg_insert(...).on_conflict_do_update(index_elements=["item_id"])`
- CLI: `--item-id`, `--from`/`--to` range, full sweep iterating known item_ids.
- **Discrepancy to resolve at apply:** registered param is `item_id` but old Streamlit called it
  with `fromDate/toDate`. Field mapping `_record_to_datos()` is marked **PENDING live inspection** —
  hit the worker once, capture one real row, then fill the mapping. The storage table and the sync
  skeleton are built now; only the `record.get("...")` keys are deferred.

**Confidence: HIGH on storage decision. PENDING: exact field mapping + param contract (external ERP).**

This whole sub-deliverable is INDEPENDENT and must not block the calculated-ageing ranking
(which uses `dias_sin_venta`, not ERP ageing). Ranking LEFT JOINs `productos_ageing`; if empty,
`ageing_erp_dias` is `null` and the column shows "—".

---

## 5. Aggregation query design

Single `select()` over `productos_erp pe` (base). Built with SQLAlchemy Core/`text()` for the
LATERAL subqueries (SQLAlchemy `lateral()` is supported; given the existing codebase freely uses
raw SQL for these analytic queries, the design allows a parametrized `text()` block too — tasks
phase picks the concrete form, both are acceptable).

### 5.1 Column expressions

| Output column | Expression |
|---|---|
| `item_id`, `codigo`, `descripcion`, `marca`, `categoria` | from `pe` |
| `pm_nombre` | `u.nombre` via `marcas_pm` LEFT JOIN; `NULL` → "Sin PM" |
| `last_sale_date` | LATERAL #1 `MAX(tct.ct_date)` filtered by sale predicate (§2) |
| `dias_sin_venta` | `(NOW()::date - last_sale_date::date)`; `NULL` when never sold |
| `unidades_vendidas_ventana` | correlated `SUM(tit.it_qty)` over sale predicate AND `ct_date >= NOW() - :ventana_dias` |
| `last_purchase_date` | LATERAL #2 `MAX(it_cd)` where `puco_id = 10` |
| `last_purchase_qty` | `it_qty` of that MAX(it_cd) row (LATERAL ORDER BY it_cd DESC LIMIT 1) |
| `stock_total` | `SUM(itst.itst_cant)` over selected `stor_id`s |
| `precio_clasica` | `prli.prli_price` where `prli_id = 4` |
| `costo_ars` | `pe.costo` if `moneda_costo='ARS'` else `pe.costo * tc_venta` |
| `valor_costo` | `stock_total * costo_ars` |
| `valor_venta` | `stock_total * precio_clasica` |
| `ageing_erp_dias` | `pa.ageing_dias` (LEFT JOIN `productos_ageing`) |

`tc_venta` = latest `tipo_cambio.venta` for `moneda='USD'` resolved ONCE per request (scalar
subquery `(SELECT venta FROM tipo_cambio WHERE moneda='USD' ORDER BY fecha DESC LIMIT 1)`), reusing
the pattern from `pricing-app-pricing-logic`. Do not convert per-row with a correlated subquery.

### 5.2 LATERAL #1 — last sale (channel-unified, ventas only)

```sql
LEFT JOIN LATERAL (
    SELECT MAX(tct.ct_date) AS last_sale_date
    FROM tb_item_transactions tit
    JOIN tb_commercial_transactions tct
      ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    WHERE tit.item_id = pe.item_id
      AND tct.sd_id IN (1,4,21,56)
      AND tct.df_id IN (<DF_VENTA_TODOS>)
      AND tit.it_qty <> 0
) ls ON TRUE
```

`unidades_vendidas_ventana` is a SECOND lateral (or a sibling aggregate in the same lateral with a
`FILTER (WHERE tct.ct_date >= NOW() - (:ventana_dias || ' days')::interval)` clause — preferred, one pass):

```sql
LEFT JOIN LATERAL (
    SELECT MAX(tct.ct_date) AS last_sale_date,
           SUM(tit.it_qty) FILTER (
             WHERE tct.ct_date >= NOW() - (:ventana_dias || ' days')::interval
           ) AS unidades_ventana
    FROM tb_item_transactions tit
    JOIN tb_commercial_transactions tct
      ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    WHERE tit.item_id = pe.item_id
      AND tct.sd_id IN (1,4,21,56)
      AND tct.df_id IN (<DF_VENTA_TODOS>)
      AND tit.it_qty <> 0
) ls ON TRUE
```

### 5.3 LATERAL #2 — last purchase

```sql
LEFT JOIN LATERAL (
    SELECT tit.it_cd AS last_purchase_date, tit.it_qty AS last_purchase_qty
    FROM tb_item_transactions tit
    WHERE tit.item_id = pe.item_id
      AND tit.puco_id = 10
    ORDER BY tit.it_cd DESC
    LIMIT 1
) lp ON TRUE
```

### 5.4 Other joins

```sql
LEFT JOIN LATERAL (
    SELECT SUM(itst.itst_cant) AS stock_total
    FROM tb_item_storage itst
    WHERE itst.item_id = pe.item_id
      AND itst.stor_id = ANY(:stor_ids)        -- selected depots, default [1]
) st ON TRUE
LEFT JOIN tb_price_list_items prli
       ON prli.item_id = pe.item_id AND prli.prli_id = 4 AND prli.comp_id = 1
LEFT JOIN marcas_pm mpm
       ON mpm.marca = pe.marca AND mpm.categoria = pe.categoria   -- text join, fragile by design
LEFT JOIN usuarios u ON u.id = mpm.usuario_id
LEFT JOIN productos_ageing pa ON pa.item_id = pe.item_id
```

PM join is text-based with no FK (locked decision). LEFT JOIN so items without a PM still appear;
surface `pm_nombre = NULL → "Sin PM"` in the FE.

### 5.5 Filters (WHERE on base)

- `pe.activo = TRUE` (default; expose `incluir_inactivos` flag, default false)
- `pe.marca = :marca` (optional)
- `pe.categoria = :categoria` (optional)
- `mpm.usuario_id = :pm_id` (optional — filter by PM; requires the join, fine)
- text search `pe.descripcion ILIKE :q OR pe.codigo ILIKE :q` (optional, debounced on FE)

### 5.6 Dynamic sort over computed columns

The locked `SORT_COLUMNS` whitelist pattern (`rrhh_empleados.py:464`) maps a `sort_by` string to a
**SQL expression label**, NOT only a model column — because most sort targets are computed
(`dias_sin_venta`, `valor_costo`, etc.). Implementation: build the `select()` with labeled columns,
keep a dict `SORT_COLUMNS = {"dias_sin_venta": <labeled_expr>, "valor_costo": ..., ...}`, and apply
`.order_by(expr.desc()/.asc())` BEFORE `.limit/.offset`. `NULLS LAST` on `dias_sin_venta` so
never-sold items (the most interesting "stale" rows) sort predictably.

Whitelist keys (reject anything else → 422):
`dias_sin_venta, unidades_vendidas_ventana, last_purchase_date, stock_total, valor_costo,
valor_venta, precio_clasica, ageing_erp_dias, codigo, descripcion, marca, categoria`.
Default sort: `dias_sin_venta DESC NULLS FIRST` (stalest first; never-sold at top).

> NOTE captured from proposal: the existing generic `_paginate` helper does NOT sort — this endpoint
> implements its own order_by, do not route through `_paginate`.

### 5.7 Pagination & count

- `limit` capped at 100 (page-size cap = perf guard), `offset = (page-1)*page_size`.
- Separate `COUNT(*)` query over the SAME base+filters (without the LATERALs — count only needs the
  `productos_erp` filter set + the PM join when `pm_id` filter active) to avoid paying LATERAL cost
  twice. Return `{ items, total, page, page_size }`.

### 5.8 Endpoint signature & session

```python
router = APIRouter(prefix="/consultas", tags=["consultas"])

@router.get(
    "/ranking",
    response_model=RankingProductosResponse,
    dependencies=[Depends(require_permiso("consultas.ver_ranking"))],
)
async def get_ranking_productos(
    marca: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    pm_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    stor_ids: list[int] = Query([1]),
    ventana_dias: int = Query(90),            # validated against {30,60,90,180}
    incluir_inactivos: bool = Query(False),
    sort_by: str = Query("dias_sin_venta"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RankingProductosResponse: ...
```

Use plain `get_db` (this is a one-shot JSON response, NOT a long-lived stream — per backend
CLAUDE.md the long-lived-pool rule does not apply). `require_permiso` already chains auth.

---

## 6. Pydantic v2 schemas

```python
# backend/app/schemas/consultas.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Any

class RankingProductoItem(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    categoria: Optional[str]
    pm_nombre: Optional[str]              # None → FE shows "Sin PM"
    last_sale_date: Optional[datetime]
    dias_sin_venta: Optional[int]
    unidades_vendidas_ventana: Optional[float]
    last_purchase_date: Optional[datetime]
    last_purchase_qty: Optional[float]
    stock_total: Optional[float]
    precio_clasica: Optional[float]
    costo_ars: Optional[float]
    valor_costo: Optional[float]
    valor_venta: Optional[float]
    ageing_erp_dias: Optional[int]
    ageing_erp_payload: Optional[Any] = None
    model_config = ConfigDict(from_attributes=True)

class RankingProductosResponse(BaseModel):
    items: list[RankingProductoItem]
    total: int
    page: int
    page_size: int
    ventana_dias: int
```

Money/qty exposed as float in the response (display-only, read-only page). Internal cost→ARS uses
the latest `tipo_cambio.venta` scalar; no cents arithmetic needed since nothing is persisted.

---

## 7. Permission seed — `consultas.ver_ranking`

Migration modeled on `20260527_add_permiso_ver_prearmadas_stats.py`:
- INSERT into `permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)`
  with `codigo='consultas.ver_ranking'`, `categoria='consultas'` (new category), `es_critico=false`,
  `ON CONFLICT (codigo) DO NOTHING`.
- Seed assignment to role `ADMIN` only (`roles_permisos_base`), `ON CONFLICT DO NOTHING`. Other roles
  assigned manually from the permissions panel post-deploy (matches established precedent).
- `downgrade()` cleans `roles_permisos_base`, `usuarios_permisos_override`, then the `permisos` row.

Backend gate via `Depends(require_permiso("consultas.ver_ranking"))`. FE gate via `usePermisos`
+ `ProtectedRoute` (same string).

---

## 8. Migrations (Alembic)

Two migrations chained after the current head (`alembic heads` to confirm at apply; current tip
appears to be `compras_036_ncs_dedup_uq_numero_nc_proveedor`):

### M1 — transactional: storage + permission
- `create_table productos_ageing` (§4).
- permission seed (§7).
- Standard transactional migration (no concurrency).

### M2 — non-transactional: composite indexes (CONCURRENTLY)
Modeled EXACTLY on `20260527_add_prearmados_armado_idx.py` (uses `op.get_context().autocommit_block()`):

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Purchase lookup (LATERAL #2): item_id + puco_id + it_cd
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_puco_cd "
            "ON tb_item_transactions (item_id, puco_id, it_cd DESC)"
        )
        # Sales lookup (LATERAL #1): item_id + ct_transaction (join key to tct)
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_cttx "
            "ON tb_item_transactions (item_id, ct_transaction)"
        )
        # tct side: sd_id/df_id are the sale discriminators; ct_date for window filter
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tct_sd_df_date "
            "ON tb_commercial_transactions (sd_id, df_id, ct_date)"
        )
```

`CONCURRENTLY` is **mandatory** — `tb_item_transactions` is large and production-hot; a plain
`CREATE INDEX` would take an `ACCESS EXCLUSIVE`/`SHARE` lock blocking writes for the full build.
Implication for Alembic: each `CREATE INDEX CONCURRENTLY` must run OUTSIDE a transaction →
`op.get_context().autocommit_block()` (codebase precedent confirmed). `IF NOT EXISTS` makes it
idempotent. `downgrade()` mirrors with `DROP INDEX CONCURRENTLY IF EXISTS` inside an autocommit block.
Keep M1 (transactional) and M2 (non-transactional) as SEPARATE migration files — never mix concurrent
DDL into a transactional migration.

> NOTE: `tb_item_transactions` already indexes `item_id`, `ct_transaction`, `it_cd` individually
> (see model). The composite `(item_id, puco_id, it_cd DESC)` is the load-bearing add — `puco_id`
> is currently UNINDEXED and is the primary perf risk for the purchase LATERAL. Tasks phase should
> `EXPLAIN ANALYZE` against prod-like data and may drop redundant composites if the planner already
> covers them.

---

## 9. Currency display — RESOLVED

**Decision: ARS-only in the columns; show the original `moneda_costo` as a small badge/tooltip on
the cost cell.** Rationale: valuation columns (`valor_costo`, `valor_venta`) MUST be summable and
comparable across the whole catalog — mixing USD and ARS magnitudes in a sortable column is
meaningless. So all monetary columns are ARS, converted via latest `tipo_cambio.venta`. The original
currency is informational only (a "USD" chip next to items whose `moneda_costo='USD'`), not a separate
sortable column. No second currency column at launch (keeps the table narrow; YAGNI for a v1 read view).

**Confidence: HIGH.**

---

## 10. Frontend design

Routing: add route under `AppLayout`/`Outlet`; add a `Consultas` section to `Sidebar.jsx`
`menuSections` with item `{ label: 'Ranking de productos', path: '/consultas/ranking',
permiso: 'consultas.ver_ranking' }`. Wrap the route in `ProtectedRoute` with the same permiso.

Components:
- `pages/ConsultasRanking.jsx` — orchestrator: holds filter state, calls API, renders table.
- `components/consultas/RankingFiltros.jsx` — Marca/Categoría/PM selects, depot multi-select
  (default depósito 1), `ventana_dias` select {30,60,90,180}, search input (debounced via
  `useDebounce`), `incluir_inactivos` toggle.
- `components/consultas/RankingTabla.jsx` — Tesla `table-tesla table-row-hover`, sortable headers
  with `lucide-react` `ChevronUp/ChevronDown/ChevronsUpDown` icons (NO emoji), one column per §5.1.
  `pm_nombre == null` → render "Sin PM" muted. `ageing_erp_dias == null` → "—". `dias_sin_venta == null`
  → "Nunca vendido" highlighted.
- Pagination via existing `useServerPagination` hook (page/page_size/total wiring).

State & data: local `useState` for filters; axios via `services/api.js` with `localStorage` token;
loading + error states; permission gating with `usePermisos().tienePermiso('consultas.ver_ranking')`
to hide the menu item and short-circuit the page.

Styling: CSS Modules + design tokens only (`var(--bg-primary)`, `var(--text-primary)`, etc.); no
inline styles, no hardcoded colors, no Tailwind. Test light AND dark. Right-align numeric/currency
columns; format ARS with `Intl.NumberFormat('es-AR', { style:'currency', currency:'ARS' })`.

Read-only: no edit/delete affordances, no write calls.

---

## 11. ADR-style decisions

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| ADR-1 | "Last sale" = `sd_id IN SD_VENTAS` ∪ all channel `df_id`s, ventas-only | Per-channel last-sale; include returns | Ageing = "when last SOLD anywhere"; returns must not reset the clock |
| ADR-2 | Live aggregation, no materialized snapshot at launch | Pre-aggregated `ranking_snapshot` table | Catalog size manageable with indexes + DB pagination; snapshot is the documented scale-out fallback |
| ADR-3 | Separate `productos_ageing` table (JSONB + scalar) | Column on `productos_erp` | Different sync cadence; `hash_datos` integrity; tolerates unknown scriptAgeing shape |
| ADR-4 | Sales velocity = `unidades_vendidas_ventana` with `ventana_dias` param (default 90) | Hardcoded N; computed velocity score | Satisfies "poca venta en X tiempo"; configurable; score is future work |
| ADR-5 | ARS-only monetary columns + original-currency badge | ARS + original sortable column | Valuation columns must be summable/comparable; narrow v1 table |
| ADR-6 | Composite indexes via `CREATE INDEX CONCURRENTLY` in separate non-transactional migration | Plain `CREATE INDEX` in one migration | Avoid prod write-lock on huge `tb_item_transactions`; Alembic needs autocommit_block |
| ADR-7 | Dynamic sort over labeled SQL expressions via SORT_COLUMNS whitelist | ORM-column-only sort; client-side sort | Most sort targets are computed; whitelist prevents injection; DB sort before paginate |
| ADR-8 | scriptAgeing sync independently shippable, ranking LEFT JOINs ageing | Block ranking on ERP ageing | Unknown external contract must not gate the calculated-ageing feature |

---

## 12. Open items status

**RESOLVED (this design):**
- Canonical sale definition (ADR-1) — HIGH confidence, one-line user confirm at apply.
- Sales velocity window (ADR-4).
- ERP-ageing storage decision (ADR-3).
- Index safety / concurrent build (ADR-6).
- Currency display (ADR-5).
- Sort over computed columns (ADR-7).

**PENDING external input:**
- `scriptAgeing` real response shape + `item_id` vs `fromDate/toDate` param contract — needs ONE
  live call to the ERP worker before `_record_to_datos()` mapping can be finalized. Storage + sync
  skeleton are designed; only field keys deferred. Does NOT block the ranking.
- One-line user sign-off on ADR-1 (ventas-only, channel-union, no vendor/customer exclusion).
