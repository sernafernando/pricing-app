"""
Router: Consultas — product ranking.

Endpoint: GET /api/consultas/ranking

Returns a paginated, sortable ranking of products aggregated from ERP data.
Each row contains:
  - Calculated ageing (days since last SALE, using tb_item_transactions ⋈
    tb_commercial_transactions with the canonical sale definition confirmed
    in ADR-1: sd_id IN SD_VENTAS, df_id IN DF_VENTA_TODOS).
  - Last purchase data (puco_id=10, latest it_cd).
  - Stock total across selected depots (stock_por_deposito.stock — ERP real-time available stock).
  - Monetary valuations in BOTH ARS and USD (valor_costo_ars, valor_costo_usd).
  - valor_venta in ARS (price list clasica prli_id=4).
  - ERP-sourced ageing from productos_ageing (LEFT JOIN — null at launch).

Permission gate: consultas.ver_ranking  (seeded by Alembic migration M1).
No JWT → 401 | Wrong permission → 403.

ADR references:
  ADR-1: Canonical sale definition.
  ADR-5: Dual-currency cost columns (ARS + USD); FX via TipoCambio.venta.
  ADR-7: Dynamic multi-column sort via SORT_COLUMNS whitelist.
  ADR-8: incluir_sin_stock / incluir_combos filter params.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_algun_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.core.logging import get_logger
from app.schemas.consultas import (
    SORT_COLUMNS_PERMITIDAS,
    DepositoFacet,
    KpisResponse,
    RankingFacetsResponse,
    RankingItemRow,
    RankingResponse,
    ResumenResponse,
    ResumenRow,
    StockRefreshResponse,
    StockStatusResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/consultas", tags=["consultas"])

# ---------------------------------------------------------------------------
# Stock sync concurrency guard
# ---------------------------------------------------------------------------

# Module-level flag — protects against concurrent API-triggered refreshes.
# NOTE: this guard is PER-PROCESS (best-effort). Under uvicorn/gunicorn with
# multiple workers each worker has its own flag, so two workers could each
# launch a sync. That is acceptable because the underlying upsert is idempotent
# and the cron (flock) already overlaps safely; the flag only de-dupes within a
# single worker. The cron may also overlap for the same reason.
_stock_sync_running: bool = False

# Strong references to in-flight background tasks. asyncio only keeps a WEAK
# reference to a task, so a fire-and-forget create_task() can be garbage
# collected mid-run — which would skip its finally block and leave
# _stock_sync_running stuck at True forever (permanent 409). Holding the task
# here until it completes prevents that.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Stock status + refresh endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/ranking/stock-status",
    response_model=StockStatusResponse,
    summary="Stock freshness status for stock_por_deposito",
    dependencies=[Depends(require_algun_permiso(["consultas.ver_ranking", "consultas.ver_mi_ranking"]))],
)
async def get_stock_status(
    db: Session = Depends(get_db),
) -> StockStatusResponse:
    """Return the freshness timestamp of the stock_por_deposito snapshot.

    Queries MAX(updated_at) from stock_por_deposito to indicate when the last
    sync completed. Also returns whether a background refresh is currently in
    progress (syncing=True).

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    try:
        row = db.execute(text("SELECT MAX(updated_at) AS last_updated FROM stock_por_deposito")).fetchone()
    except Exception as exc:
        logger.error("Error querying stock_por_deposito freshness: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar el estado del stock",
        ) from exc

    last_updated = row[0] if row and row[0] is not None else None
    return StockStatusResponse(last_updated=last_updated, syncing=_stock_sync_running)


@router.post(
    "/ranking/stock-refresh",
    response_model=StockRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a background stock sync from the ERP",
    dependencies=[Depends(require_algun_permiso(["consultas.ver_ranking", "consultas.ver_mi_ranking"]))],
)
async def post_stock_refresh() -> StockRefreshResponse:
    """Launch a background refresh of stock_por_deposito from the ERP.

    The sync is run asynchronously via asyncio.create_task so the request
    returns immediately (202). The sync can take several minutes as it hits
    the ERP API for each depot.

    Concurrency guard: if a refresh is already running (whether triggered by
    this endpoint or another concurrent request), returns 409 immediately. The
    cron may still overlap — that is acceptable because the upsert is idempotent.

    CRITICAL: run_sync() opens its own DB session (SessionLocal) and must NOT
    receive the request's db session — that would pin the connection for the
    entire sync duration, exhausting the pool.

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    global _stock_sync_running

    if _stock_sync_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sincronización de stock ya en curso",
        )

    _stock_sync_running = True

    async def _run_and_reset() -> None:
        global _stock_sync_running
        # Lazy import avoids circular dependency risk at module load time.
        from app.scripts.sync_stock_por_deposito import run_sync  # noqa: PLC0415

        try:
            await run_sync()
            logger.info("✅ Stock refresh completado (API trigger)")
        except Exception as exc:
            logger.error("❌ Error durante stock refresh (API trigger): %s", exc, exc_info=True)
        finally:
            _stock_sync_running = False

    # Retain a strong reference until the task finishes (see _background_tasks).
    task = asyncio.create_task(_run_and_reset())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return StockRefreshResponse(status="started")


# ---------------------------------------------------------------------------
# Sale definition constants (ADR-1)
# ---------------------------------------------------------------------------

SD_VENTAS: list[int] = [1, 4, 21, 56]
SD_DEVOLUCIONES: list[int] = [3, 6, 23, 66]

# DF_PERMITIDOS = fuera-ML channel (from ventas_fuera_ml.py)
DF_PERMITIDOS: list[int] = [
    1,
    2,
    3,
    4,
    5,
    6,
    63,
    85,
    86,
    87,
    65,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    81,
    103,
    105,
    106,
    109,
    111,
    115,
    116,
    117,
    118,
    122,
    124,
    125,
    126,
    127,
]
# TN channel df_ids
DF_TN: list[int] = [113, 114]
# ML channel df_ids
DF_ML: list[int] = [129, 130, 131, 132]

# Union of all sale channel df_ids (ADR-1)
DF_VENTA_TODOS: list[int] = list(set(DF_PERMITIDOS) | set(DF_TN) | set(DF_ML))

# Items excluded from sale calculation
ITEMS_EXCLUIDOS: list[int] = [16, 460]

# puco_id for purchases
PUCO_COMPRAS: int = 10
# prli_id for price list "clasica"
PRLI_CLASICA: int = 4
# comp_id of the main company (price list / cost list rows are keyed by comp_id)
COMP_ID: int = 1
# Dead stock threshold: no sale in the last N days (matches capital_muerto KPI).
DIAS_MUERTO_UMBRAL: int = 365

# ERP sentinel for "item does not control stock" (virtual/unlimited items).
# The ERP stores 99999999 as available stock for these; it is NOT a real quantity.
# Real stock tops out well below this (no legitimate values between max real stock
# and the sentinel), so it is excluded from valuation to avoid inflating capital.
STOCK_SENTINEL: int = 99999999


# ---------------------------------------------------------------------------
# Permission constants (ADR-9: scoped ranking access)
# ---------------------------------------------------------------------------

PERMISO_RANKING_FULL = "consultas.ver_ranking"
PERMISO_RANKING_PROPIO = "consultas.ver_mi_ranking"

# ---------------------------------------------------------------------------
# Dynamic sort column map (ADR-7)
# ---------------------------------------------------------------------------

# Maps the public sort key → SQL expression fragment used in ORDER BY.
# All expressions reference aliases defined in the CTE / subquery below.
_SORT_EXPR_MAP: dict[str, str] = {
    "dias_sin_venta": "dias_sin_venta",
    "total_stock": "total_stock",
    "valor_costo_ars": "valor_costo_ars",
    "valor_costo_usd": "valor_costo_usd",
    "valor_venta": "valor_venta",
    "last_purchase_date": "last_purchase_date",
    "codigo": "pe.codigo",
    "descripcion": "pe.descripcion",
    "marca": "pe.marca",
    "categoria": "pe.categoria",
}

# Columns where NULLs should sort LAST regardless of direction (ADR-7).
_NULLS_LAST_COLS: frozenset[str] = frozenset(
    {"last_purchase_date", "valor_costo_ars", "valor_costo_usd", "valor_venta"}
)

# Columns where NULL means "infinite" / "never happened" and should sort as the
# maximum value: NULLS FIRST on DESC (most-aged first), NULLS LAST on ASC.
# dias_sin_venta: NULL = product never sold = infinitely aged = sorts at the top
# when ranking by most stagnant stock (desc).
_NULLS_AS_MAX_COLS: frozenset[str] = frozenset({"dias_sin_venta"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_nulls_clause(sort_key: str, sort_dir: str) -> str:
    """Return 'NULLS LAST' or 'NULLS FIRST' depending on column and direction.

    Per ADR-7: most nullable ranking columns sort NULLS LAST so products with
    data appear before products without data, regardless of sort direction.

    Exception (_NULLS_AS_MAX_COLS): dias_sin_venta NULL means the product has
    NEVER been sold — conceptually infinite age. It should behave like the
    largest possible value: NULLS FIRST on DESC (most-aged at top), NULLS LAST
    on ASC (most-aged at bottom).
    """
    if sort_key in _NULLS_AS_MAX_COLS:
        # NULL = max value: sorts first on DESC, last on ASC
        return "NULLS FIRST" if sort_dir == "desc" else "NULLS LAST"
    if sort_key in _NULLS_LAST_COLS:
        return "NULLS LAST"
    # Non-nullable computed columns: standard PostgreSQL behaviour
    return "NULLS LAST" if sort_dir == "desc" else "NULLS FIRST"


def _parse_sort_params(
    orden_campos: Optional[str],
    orden_direcciones: Optional[str],
) -> list[tuple[str, str, str]]:
    """Parse and validate multi-sort params from parallel comma-separated lists.

    orden_campos: comma-separated list of sort field names (e.g. "dias_sin_venta,total_stock")
    orden_direcciones: comma-separated list of directions (e.g. "desc,asc")

    If lengths mismatch (more campos than direcciones), missing directions default to 'desc'.
    Returns a deduped, ordered list of (campo, sql_expr, direction) tuples.
    Raises HTTPException 422 on invalid field or direction.
    """
    campos_str = (orden_campos or "dias_sin_venta").strip()
    dirs_str = (orden_direcciones or "desc").strip()

    campos = [c.strip() for c in campos_str.split(",") if c.strip()]
    dirs = [d.strip().lower() for d in dirs_str.split(",") if d.strip()]

    # Pad missing directions with 'desc'
    while len(dirs) < len(campos):
        dirs.append("desc")

    result: list[tuple[str, str, str]] = []
    seen_fields: set[str] = set()

    for campo, direccion in zip(campos, dirs):
        if campo not in SORT_COLUMNS_PERMITIDAS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Campo de sort '{campo}' no es válido. Opciones: {sorted(SORT_COLUMNS_PERMITIDAS)}",
            )
        if direccion not in ("asc", "desc"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Dirección de sort '{direccion}' no es válida. Use 'asc' o 'desc'.",
            )
        if campo not in seen_fields:
            result.append((campo, _SORT_EXPR_MAP[campo], direccion))
            seen_fields.add(campo)

    if not result:
        # Fallback: default sort
        result.append(("dias_sin_venta", _SORT_EXPR_MAP["dias_sin_venta"], "desc"))

    return result


def _build_order_clause(sort_tuples: list[tuple[str, str, str]]) -> str:
    """Build ORDER BY clause from validated (campo, sql_expr, direction) tuples.

    The campo travels with its own expr/direction (no positional zip against a
    separate list), so duplicate or deduped fields can never misalign the
    NULLS clause. Always appends pe.item_id ASC as a stable tiebreaker (ADR-7).
    """
    parts: list[str] = []
    for campo, sql_expr, direction in sort_tuples:
        nulls = _build_nulls_clause(campo, direction)
        parts.append(f"{sql_expr} {direction.upper()} {nulls}")
    parts.append("pe.item_id ASC")
    return ", ".join(parts)


def _scope_user_id(current_user: Usuario, db: Session) -> Optional[int]:
    """Return the user's id when their access is scoped to their own PM assignments.

    Returns ``None`` when the user has FULL ranking access (``consultas.ver_ranking``
    or SUPERADMIN), meaning no extra WHERE filter is needed.

    Returns ``current_user.id`` when the user has only ``consultas.ver_mi_ranking``,
    so callers can append the EXISTS scope filter to each query.

    Args:
        current_user: The authenticated user.
        db: Active SQLAlchemy session (same one used by the endpoint).

    Returns:
        ``None`` → full access; int → scoped to this user_id.
    """
    svc = PermisosService(db)
    if svc.tiene_permiso(current_user, PERMISO_RANKING_FULL):
        return None
    return current_user.id


def _get_tc_venta(db: Session) -> Optional[float]:
    """Return the latest USD→ARS venta rate from tipo_cambio, or None."""
    row = db.execute(
        text("SELECT venta FROM tipo_cambio WHERE moneda = 'USD' ORDER BY fecha DESC, id DESC LIMIT 1")
    ).fetchone()
    if row is None:
        return None
    return float(row[0]) if row[0] is not None else None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/ranking",
    response_model=RankingResponse,
    summary="Product ranking by sales ageing",
    dependencies=[Depends(require_algun_permiso([PERMISO_RANKING_FULL, PERMISO_RANKING_PROPIO]))],
)
async def get_ranking(
    # Pagination
    page: int = Query(default=1, ge=1, description="Página (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Filas por página (max 200)"),
    # Multi-column sort: parallel comma-separated lists (ADR-7)
    # Example: orden_campos=dias_sin_venta,total_stock&orden_direcciones=desc,asc
    orden_campos: Optional[str] = Query(
        default="dias_sin_venta",
        description="Campos de sort separados por coma (e.g. 'dias_sin_venta,total_stock').",
    ),
    orden_direcciones: Optional[str] = Query(
        default="desc",
        description="Direcciones de sort separadas por coma, en paralelo con orden_campos (e.g. 'desc,asc'). Si hay menos que campos, los faltantes usan 'desc'.",
    ),
    # Filters
    marca: Optional[str] = Query(default=None, max_length=100),
    categoria: Optional[str] = Query(default=None, max_length=100),
    pm: Optional[str] = Query(
        default=None,
        description="Nombre del PM asignado, o 'sin_pm' para productos sin PM",
    ),
    stor_ids: list[int] = Query(default=[1], description="IDs de depósito"),
    # Boolean filters (ADR-8)
    incluir_sin_stock: bool = Query(
        default=False,
        description="Si True, incluye productos sin stock en los depósitos seleccionados.",
    ),
    incluir_combos: bool = Query(
        default=False,
        description="Si True, incluye combos/producción (productos padre en tb_item_association).",
    ),
    solo_muerto: bool = Query(
        default=False,
        description="Solo productos sin ventas en los últimos N días (stock muerto).",
    ),
    # Full-text search filter
    q: Optional[str] = Query(
        default=None,
        description="Búsqueda por código o descripción (ILIKE).",
    ),
    # Auth resolved by FastAPI dep-dedup — same session as require_algun_permiso.
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """Product ranking ordered by sales ageing and configurable metrics.

    Aggregates ERP transaction data to compute:
    - dias_sin_venta: days since last sale across all channels (unbounded).
    - total_stock: sum of stock_por_deposito.stock for selected depots (ERP real-time available stock).
    - valor_costo_ars: stock × costo in ARS (FX applied when origin is USD).
    - valor_costo_usd: stock × costo in USD (FX applied when origin is ARS).
    - valor_venta: total_stock × precio from tb_price_list_items (prli_id=4) in ARS.
    - erp_ageing_dias: ERP-computed ageing from productos_ageing (null at launch).

    Multi-sort: orden_campos + orden_direcciones (parallel comma-separated lists) applied in order.
    Boolean filters: incluir_sin_stock (default False), incluir_combos (default False).

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    # Parse and validate multi-sort params (raises 422 on bad input).
    # Each tuple carries (campo, sql_expr, direction) so the NULLS clause never
    # misaligns even if duplicate fields are sent.
    sort_tuples = _parse_sort_params(orden_campos, orden_direcciones)

    # Resolve FX rate once per request (ADR-5); null → costo columns may be null
    tc_venta: Optional[float] = _get_tc_venta(db)

    # Build parameterised lists for IN clauses
    sd_ventas_str = ",".join(str(x) for x in SD_VENTAS)
    df_venta_str = ",".join(str(x) for x in DF_VENTA_TODOS)
    items_excl_str = ",".join(str(x) for x in ITEMS_EXCLUIDOS)

    # ---- Dynamic ORDER BY ----
    order_clause = _build_order_clause(sort_tuples)

    # ---- WHERE clauses for filters ----
    filter_clauses: list[str] = ["pe.activo = TRUE"]
    params: dict = {
        "stor_ids": stor_ids,
        "tc_venta": tc_venta,
        "offset": (page - 1) * page_size,
        "limit": page_size,
    }

    if marca:
        filter_clauses.append("pe.marca = :marca")
        params["marca"] = marca

    if categoria:
        filter_clauses.append("pe.categoria = :categoria")
        params["categoria"] = categoria

    if pm == "sin_pm":
        filter_clauses.append("mp.usuario_id IS NULL")
    elif pm is not None:
        filter_clauses.append("u_pm.nombre = :pm_nombre")
        params["pm_nombre"] = pm

    if q and q.strip():
        filter_clauses.append("(pe.codigo ILIKE :q OR pe.descripcion ILIKE :q)")
        params["q"] = f"%{q.strip()}%"

    # incluir_sin_stock=False → only rows with stock > 0 in selected depots (ADR-8)
    if not incluir_sin_stock:
        filter_clauses.append("COALESCE(stk.total_stock, 0) > 0")

    # incluir_combos=False → exclude products that are parents in tb_item_association (ADR-8)
    if not incluir_combos:
        filter_clauses.append(
            "NOT EXISTS (SELECT 1 FROM tb_item_association ia WHERE ia.item_id = pe.item_id AND ia.iasso_qty > 0)"
        )

    # solo_muerto=True → restrict to dead stock: no sale in the last DIAS_MUERTO_UMBRAL days.
    # NOT EXISTS is self-contained (references pe.item_id only) — works in both data and count queries.
    # NO user input is interpolated; DIAS_MUERTO_UMBRAL is an int constant.
    if solo_muerto:
        filter_clauses.append(
            f"NOT EXISTS ("
            f"SELECT 1 FROM tb_item_transactions tit_m"
            f" JOIN tb_commercial_transactions tct_m ON tct_m.ct_transaction = tit_m.ct_transaction"
            f" WHERE tit_m.item_id = pe.item_id"
            f" AND tct_m.sd_id IN ({sd_ventas_str})"
            f" AND tct_m.df_id IN ({df_venta_str})"
            f" AND tit_m.it_qty <> 0"
            f" AND tct_m.ct_date >= NOW()::date - INTERVAL '{DIAS_MUERTO_UMBRAL} days'"
            f")"
        )

    # ADR-9: scoped ranking — restrict to user's own PM assignments when they lack FULL access
    scope_uid = _scope_user_id(current_user, db)
    if scope_uid is not None:
        filter_clauses.append(
            "EXISTS ("
            "SELECT 1 FROM marcas_pm mp_scope"
            " WHERE mp_scope.marca = pe.marca"
            " AND mp_scope.categoria = pe.categoria"
            " AND mp_scope.usuario_id = :scope_user_id"
            ")"
        )
        params["scope_user_id"] = scope_uid

    where_sql = " AND ".join(filter_clauses)

    # ---- Main query ----
    # Two LATERALs:
    #   ls — last_sale: MAX(ct_date) over all channels (unbounded)
    #   lp — last_purchase: most recent purchase row (puco_id=10)
    # Stock: SUM(stock) FROM stock_por_deposito WHERE stor_id = ANY(:stor_ids)
    # Monetary: dual-currency cost (ARS + USD) via :tc_venta; precio from tb_price_list_items prli_id=4
    # LEFT JOIN productos_ageing for erp_ageing_dias
    # NOTE: stk LATERAL is referenced in WHERE when incluir_sin_stock=False,
    # so it must appear before the WHERE clause processes it — it is joined unconditionally.

    main_sql = f"""
        SELECT
            pe.item_id,
            pe.codigo,
            pe.descripcion,
            pe.marca,
            pe.categoria,
            pe.moneda_costo,
            u_pm.nombre                                        AS pm,
            -- calculated ageing
            CASE
                WHEN ls.last_sale_date IS NOT NULL
                THEN CAST(NOW()::date - ls.last_sale_date::date AS INTEGER)
                ELSE NULL
            END                                                AS dias_sin_venta,
            -- ERP ageing (null until sync_ageing runs)
            pa.ageing_dias                                     AS erp_ageing_dias,
            -- last purchase
            lp.last_purchase_date,
            lp.last_purchase_qty,
            -- stock
            COALESCE(stk.total_stock, 0)                      AS total_stock,
            -- valor_costo_ars: stock × costo in ARS (ADR-5)
            -- CRITICAL: ROUND must receive NUMERIC, not double precision
            CASE
                WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                THEN CASE pe.moneda_costo
                    WHEN 'USD' THEN
                        CASE WHEN :tc_venta IS NOT NULL
                        THEN ROUND(
                            CAST(
                                CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                * CAST(pe.costo AS NUMERIC)
                                * CAST(:tc_venta AS NUMERIC)
                            AS NUMERIC), 2)
                        ELSE NULL
                        END
                    ELSE
                        ROUND(
                            CAST(
                                CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                * CAST(pe.costo AS NUMERIC)
                            AS NUMERIC), 2)
                    END
                ELSE NULL
            END                                                AS valor_costo_ars,
            -- valor_costo_usd: stock × costo in USD (ADR-5)
            CASE
                WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                THEN CASE pe.moneda_costo
                    WHEN 'USD' THEN
                        ROUND(
                            CAST(
                                CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                * CAST(pe.costo AS NUMERIC)
                            AS NUMERIC), 2)
                    ELSE
                        CASE WHEN :tc_venta IS NOT NULL AND CAST(:tc_venta AS NUMERIC) > 0
                        THEN ROUND(
                            CAST(
                                CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                * CAST(pe.costo AS NUMERIC)
                                / CAST(:tc_venta AS NUMERIC)
                            AS NUMERIC), 2)
                        ELSE NULL
                        END
                    END
                ELSE NULL
            END                                                AS valor_costo_usd,
            -- valor_venta: stock × precio clasica in ARS
            CASE
                WHEN prli.prli_price IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                THEN ROUND(
                    CAST(CAST(COALESCE(stk.total_stock, 0) AS NUMERIC) * prli.prli_price AS NUMERIC),
                    2
                )
                ELSE NULL
            END                                                AS valor_venta
        FROM productos_erp pe
        -- LATERAL: last sale date (unbounded — dias_sin_venta = NOW()::date - last_sale_date::date)
        LEFT JOIN LATERAL (
            SELECT
                MAX(tct.ct_date)                              AS last_sale_date
            FROM tb_item_transactions tit
            JOIN tb_commercial_transactions tct
              ON tct.ct_transaction = tit.ct_transaction
            WHERE tit.item_id = pe.item_id
              AND tct.sd_id IN ({sd_ventas_str})
              AND tct.df_id IN ({df_venta_str})
              AND tit.it_qty <> 0
              AND tit.item_id NOT IN ({items_excl_str})
        ) ls ON TRUE
        -- LATERAL: last purchase
        -- Filter puco_id on tb_item_transactions (tit2) so the composite index
        -- ix_tit_item_puco_cd (item_id, puco_id, it_cd DESC) drives the lookup.
        -- The tct2 join only resolves ct_date for the single resulting row.
        LEFT JOIN LATERAL (
            SELECT
                tct2.ct_date::date                            AS last_purchase_date,
                tit2.it_qty                                   AS last_purchase_qty
            FROM tb_item_transactions tit2
            JOIN tb_commercial_transactions tct2
              ON tct2.ct_transaction = tit2.ct_transaction
            WHERE tit2.item_id = pe.item_id
              AND tit2.puco_id = {PUCO_COMPRAS}
            ORDER BY tit2.it_cd DESC
            LIMIT 1
        ) lp ON TRUE
        -- Stock across selected depots (also drives incluir_sin_stock filter via WHERE)
        LEFT JOIN LATERAL (
            SELECT SUM(stock) AS total_stock
            FROM stock_por_deposito
            WHERE item_id = pe.item_id
              AND stor_id = ANY(:stor_ids)
              AND stock < {STOCK_SENTINEL}
        ) stk ON TRUE
        -- Price list clasica (prli_id=4). comp_id is part of the PK
        -- (comp_id, prli_id, item_id) — without it the LEFT JOIN can multiply rows.
        LEFT JOIN tb_price_list_items prli
          ON prli.item_id = pe.item_id
         AND prli.prli_id = {PRLI_CLASICA}
         AND prli.comp_id = {COMP_ID}
        -- PM assignment via marcas_pm. Cannot multiply rows: marcas_pm has a
        -- UNIQUE constraint (marcas_pm_marca_categoria_key) on (marca, categoria),
        -- so at most one PM matches a given product — the COUNT(*) and the row
        -- set stay correct.
        LEFT JOIN marcas_pm mp
          ON mp.marca = pe.marca
         AND mp.categoria = pe.categoria
        LEFT JOIN usuarios u_pm
          ON u_pm.id = mp.usuario_id
        -- ERP ageing (null until sync_ageing)
        LEFT JOIN productos_ageing pa
          ON pa.item_id = pe.item_id
        WHERE {where_sql}
        ORDER BY {order_clause}
        LIMIT :limit OFFSET :offset
    """

    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM productos_erp pe
        -- Stock LATERAL needed for incluir_sin_stock filter consistency
        LEFT JOIN LATERAL (
            SELECT SUM(stock) AS total_stock
            FROM stock_por_deposito
            WHERE item_id = pe.item_id
              AND stor_id = ANY(:stor_ids)
              AND stock < {STOCK_SENTINEL}
        ) stk ON TRUE
        LEFT JOIN marcas_pm mp
          ON mp.marca = pe.marca
         AND mp.categoria = pe.categoria
        LEFT JOIN usuarios u_pm
          ON u_pm.id = mp.usuario_id
        WHERE {where_sql}
    """

    try:
        rows = db.execute(text(main_sql), params).fetchall()
        count_row = db.execute(
            text(count_sql),
            {k: v for k, v in params.items() if k not in ("offset", "limit")},
        ).fetchone()
    except Exception as exc:
        logger.error("Error in consultas ranking query: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al ejecutar la consulta de ranking",
        ) from exc

    total = int(count_row[0]) if count_row else 0

    items = [
        RankingItemRow(
            item_id=row.item_id,
            codigo=row.codigo or "",
            descripcion=row.descripcion or "",
            marca=row.marca,
            categoria=row.categoria,
            moneda_costo=row.moneda_costo,
            pm=row.pm,
            dias_sin_venta=row.dias_sin_venta,
            erp_ageing_dias=row.erp_ageing_dias,
            last_purchase_date=row.last_purchase_date,
            last_purchase_qty=int(row.last_purchase_qty) if row.last_purchase_qty is not None else None,
            total_stock=int(row.total_stock) if row.total_stock is not None else 0,
            valor_costo_ars=float(row.valor_costo_ars) if row.valor_costo_ars is not None else None,
            valor_costo_usd=float(row.valor_costo_usd) if row.valor_costo_usd is not None else None,
            valor_venta=float(row.valor_venta) if row.valor_venta is not None else None,
        )
        for row in rows
    ]

    return RankingResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Resumen endpoint
# ---------------------------------------------------------------------------

_VALID_GROUP_BY: frozenset[str] = frozenset({"marca", "pm"})


@router.get(
    "/ranking/resumen",
    response_model=ResumenResponse,
    summary="Brand/PM grouped totals for product ranking",
    dependencies=[Depends(require_algun_permiso([PERMISO_RANKING_FULL, PERMISO_RANKING_PROPIO]))],
)
async def get_ranking_resumen(
    # Filters — same semantics as /ranking
    marca: Optional[str] = Query(default=None, max_length=100),
    categoria: Optional[str] = Query(default=None, max_length=100),
    pm: Optional[str] = Query(
        default=None,
        description="Nombre del PM asignado, o 'sin_pm' para productos sin PM",
    ),
    stor_ids: list[int] = Query(default=[1], description="IDs de depósito"),
    incluir_sin_stock: bool = Query(
        default=False,
        description="Si True, incluye productos sin stock en los depósitos seleccionados.",
    ),
    incluir_combos: bool = Query(
        default=False,
        description="Si True, incluye combos/producción (productos padre en tb_item_association).",
    ),
    solo_muerto: bool = Query(
        default=False,
        description="Solo productos sin ventas en los últimos N días (stock muerto).",
    ),
    group_by: str = Query(
        default="marca",
        description="Agrupar por 'marca' o 'pm'.",
    ),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumenResponse:
    """Grouped totals (brand or PM) for the product ranking view.

    Builds the same per-product computed values as /ranking (total_stock,
    valor_costo_ars, valor_costo_usd, valor_venta) honouring ALL the same
    filters, then aggregates them by marca or PM.

    group_by='marca': rows are one per distinct marca; pm column shows the PM
      assigned to that marca (via marcas_pm; NULL → None).
    group_by='pm': rows are one per distinct PM name; grupo shows the PM name
      or 'Sin PM' when no PM is assigned.

    Also returns a totales row with sums across all groups.

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    if group_by not in _VALID_GROUP_BY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"group_by '{group_by}' no es válido. Opciones: {sorted(_VALID_GROUP_BY)}",
        )

    tc_venta: Optional[float] = _get_tc_venta(db)

    # Build IN-list strings for the solo_muerto NOT EXISTS clause (ADR-1).
    # Only used when solo_muerto=True, but built unconditionally (cheap string join).
    sd_ventas_str = ",".join(str(x) for x in SD_VENTAS)
    df_venta_str = ",".join(str(x) for x in DF_VENTA_TODOS)

    # NOTE: the resumen aggregates stock/cost/value only — no sale predicate
    # (no dias_sin_venta here), so the SD_VENTAS/DF_VENTA_TODOS lists are not used
    # for the main aggregation — only for the optional solo_muerto filter below.

    # ---- WHERE clauses (same as /ranking, minus the pagination columns) ----
    filter_clauses: list[str] = ["pe.activo = TRUE"]
    params: dict = {
        "stor_ids": stor_ids,
        "tc_venta": tc_venta,
    }

    if marca:
        filter_clauses.append("pe.marca = :marca")
        params["marca"] = marca

    if categoria:
        filter_clauses.append("pe.categoria = :categoria")
        params["categoria"] = categoria

    if pm == "sin_pm":
        filter_clauses.append("mp.usuario_id IS NULL")
    elif pm is not None:
        filter_clauses.append("u_pm.nombre = :pm_nombre")
        params["pm_nombre"] = pm

    if not incluir_sin_stock:
        filter_clauses.append("COALESCE(stk.total_stock, 0) > 0")

    if not incluir_combos:
        filter_clauses.append(
            "NOT EXISTS (SELECT 1 FROM tb_item_association ia WHERE ia.item_id = pe.item_id AND ia.iasso_qty > 0)"
        )

    if solo_muerto:
        filter_clauses.append(
            f"NOT EXISTS ("
            f"SELECT 1 FROM tb_item_transactions tit_m"
            f" JOIN tb_commercial_transactions tct_m ON tct_m.ct_transaction = tit_m.ct_transaction"
            f" WHERE tit_m.item_id = pe.item_id"
            f" AND tct_m.sd_id IN ({sd_ventas_str})"
            f" AND tct_m.df_id IN ({df_venta_str})"
            f" AND tit_m.it_qty <> 0"
            f" AND tct_m.ct_date >= NOW()::date - INTERVAL '{DIAS_MUERTO_UMBRAL} days'"
            f")"
        )

    # ADR-9: scoped ranking
    scope_uid = _scope_user_id(current_user, db)
    if scope_uid is not None:
        filter_clauses.append(
            "EXISTS ("
            "SELECT 1 FROM marcas_pm mp_scope"
            " WHERE mp_scope.marca = pe.marca"
            " AND mp_scope.categoria = pe.categoria"
            " AND mp_scope.usuario_id = :scope_user_id"
            ")"
        )
        params["scope_user_id"] = scope_uid

    where_sql = " AND ".join(filter_clauses)

    # ---- Per-product CTE (same expressions as /ranking) ----
    # CRITICAL: all ROUND() calls must cast to NUMERIC (PostgreSQL ADR-5).
    per_product_cte = f"""
        WITH per_product AS (
            SELECT
                pe.item_id,
                pe.marca,
                u_pm.nombre                                             AS pm_nombre,
                -- stock
                COALESCE(stk.total_stock, 0)                           AS total_stock,
                -- valor_costo_ars
                CASE
                    WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN CASE pe.moneda_costo
                        WHEN 'USD' THEN
                            CASE WHEN :tc_venta IS NOT NULL
                            THEN ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                    * CAST(:tc_venta AS NUMERIC)
                                AS NUMERIC), 2)
                            ELSE NULL
                            END
                        ELSE
                            ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                AS NUMERIC), 2)
                        END
                    ELSE NULL
                END                                                     AS valor_costo_ars,
                -- valor_costo_usd
                CASE
                    WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN CASE pe.moneda_costo
                        WHEN 'USD' THEN
                            ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                AS NUMERIC), 2)
                        ELSE
                            CASE WHEN :tc_venta IS NOT NULL AND CAST(:tc_venta AS NUMERIC) > 0
                            THEN ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                    / CAST(:tc_venta AS NUMERIC)
                                AS NUMERIC), 2)
                            ELSE NULL
                            END
                        END
                    ELSE NULL
                END                                                     AS valor_costo_usd,
                -- valor_venta
                CASE
                    WHEN prli.prli_price IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN ROUND(
                        CAST(CAST(COALESCE(stk.total_stock, 0) AS NUMERIC) * prli.prli_price AS NUMERIC),
                        2
                    )
                    ELSE NULL
                END                                                     AS valor_venta
            FROM productos_erp pe
            LEFT JOIN LATERAL (
                SELECT SUM(stock) AS total_stock
                FROM stock_por_deposito
                WHERE item_id = pe.item_id
                  AND stor_id = ANY(:stor_ids)
                  AND stock < {STOCK_SENTINEL}
            ) stk ON TRUE
            LEFT JOIN tb_price_list_items prli
              ON prli.item_id = pe.item_id
             AND prli.prli_id = {PRLI_CLASICA}
             AND prli.comp_id = {COMP_ID}
            LEFT JOIN marcas_pm mp
              ON mp.marca = pe.marca
             AND mp.categoria = pe.categoria
            LEFT JOIN usuarios u_pm
              ON u_pm.id = mp.usuario_id
            WHERE {where_sql}
        )
    """

    # ---- GROUP BY expression depends on group_by param ----
    if group_by == "marca":
        group_expr = "marca"
        grupo_expr = "COALESCE(marca, 'Sin marca')"
        pm_expr = (
            "CASE"
            " WHEN COUNT(DISTINCT pm_nombre) > 1 THEN 'Varios'"
            " WHEN COUNT(DISTINCT pm_nombre) = 1 THEN MAX(pm_nombre)"
            " ELSE NULL"
            " END"
        )
    else:
        # group_by == "pm"
        group_expr = "pm_nombre"
        grupo_expr = "COALESCE(pm_nombre, 'Sin PM')"
        pm_expr = "COALESCE(pm_nombre, 'Sin PM')"

    resumen_sql = f"""
        {per_product_cte}
        SELECT
            {grupo_expr}                                AS grupo,
            {pm_expr}                                   AS pm,
            COUNT(DISTINCT item_id)::INTEGER            AS num_productos,
            COALESCE(SUM(total_stock), 0)::INTEGER      AS stock_total,
            SUM(valor_costo_ars)                        AS valor_costo_ars,
            SUM(valor_costo_usd)                        AS valor_costo_usd,
            SUM(valor_venta)                            AS valor_venta
        FROM per_product
        GROUP BY {group_expr}
        ORDER BY SUM(valor_costo_ars) DESC NULLS LAST
    """

    totales_sql = f"""
        {per_product_cte}
        SELECT
            'TOTAL'                                     AS grupo,
            NULL::TEXT                                  AS pm,
            COUNT(DISTINCT item_id)::INTEGER            AS num_productos,
            COALESCE(SUM(total_stock), 0)::INTEGER      AS stock_total,
            SUM(valor_costo_ars)                        AS valor_costo_ars,
            SUM(valor_costo_usd)                        AS valor_costo_usd,
            SUM(valor_venta)                            AS valor_venta
        FROM per_product
    """

    try:
        rows = db.execute(text(resumen_sql), params).fetchall()
        totales_row = db.execute(text(totales_sql), params).fetchone()
    except Exception as exc:
        logger.error("Error in consultas ranking/resumen query: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al ejecutar la consulta de resumen",
        ) from exc

    items: list[ResumenRow] = [
        ResumenRow(
            grupo=row.grupo or "",
            pm=row.pm,
            num_productos=int(row.num_productos),
            stock_total=int(row.stock_total) if row.stock_total is not None else 0,
            valor_costo_ars=float(row.valor_costo_ars) if row.valor_costo_ars is not None else None,
            valor_costo_usd=float(row.valor_costo_usd) if row.valor_costo_usd is not None else None,
            valor_venta=float(row.valor_venta) if row.valor_venta is not None else None,
        )
        for row in rows
    ]

    totales = ResumenRow(
        grupo="TOTAL",
        pm=None,
        num_productos=int(totales_row.num_productos) if totales_row and totales_row.num_productos else 0,
        stock_total=int(totales_row.stock_total) if totales_row and totales_row.stock_total is not None else 0,
        valor_costo_ars=(
            float(totales_row.valor_costo_ars) if totales_row and totales_row.valor_costo_ars is not None else None
        ),
        valor_costo_usd=(
            float(totales_row.valor_costo_usd) if totales_row and totales_row.valor_costo_usd is not None else None
        ),
        valor_venta=(float(totales_row.valor_venta) if totales_row and totales_row.valor_venta is not None else None),
    )

    return ResumenResponse(items=items, totales=totales)


# ---------------------------------------------------------------------------
# KPIs endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/ranking/kpis",
    response_model=KpisResponse,
    summary="Aggregate KPIs for the product ranking filter set",
    dependencies=[Depends(require_algun_permiso([PERMISO_RANKING_FULL, PERMISO_RANKING_PROPIO]))],
)
async def get_ranking_kpis(
    # Filters — same semantics as /ranking (no pagination, no sort)
    marca: Optional[str] = Query(default=None, max_length=100),
    categoria: Optional[str] = Query(default=None, max_length=100),
    pm: Optional[str] = Query(
        default=None,
        description="Nombre del PM asignado, o 'sin_pm' para productos sin PM",
    ),
    stor_ids: list[int] = Query(default=[1], description="IDs de depósito"),
    incluir_sin_stock: bool = Query(
        default=False,
        description="Si True, incluye productos sin stock en los depósitos seleccionados.",
    ),
    incluir_combos: bool = Query(
        default=False,
        description="Si True, incluye combos/producción (productos padre en tb_item_association).",
    ),
    solo_muerto: bool = Query(
        default=False,
        description="Solo productos sin ventas en los últimos N días (stock muerto).",
    ),
    q: Optional[str] = Query(
        default=None,
        description="Búsqueda por código o descripción (ILIKE).",
    ),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KpisResponse:
    """Aggregate KPI metrics over all products matching the active filter set.

    Reuses the exact same per-product computed expressions and filters as /ranking
    (total_stock, valor_costo_ars, valor_costo_usd, valor_venta, dias_sin_venta via
    last-sale LATERAL — sd_id IN SD_VENTAS, df_id IN DF_VENTA_TODOS) to guarantee
    consistency between the KPI cards and the ranked table.

    Returned aggregates:
    - total_productos: COUNT(DISTINCT item_id)
    - stock_total: SUM(total_stock)
    - capital_costo_ars: SUM(valor_costo_ars)
    - capital_costo_usd: SUM(valor_costo_usd)
    - capital_venta_ars: SUM(valor_venta)
    - capital_muerto_ars: SUM(valor_costo_ars) WHERE dias_sin_venta > 365 OR last_sale_date IS NULL
    - pct_capital_muerto: capital_muerto_ars / capital_costo_ars * 100 (null-safe)

    ALL ROUND() calls cast to NUMERIC (ADR-5 — PostgreSQL has no round(double precision, int)).

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    tc_venta: Optional[float] = _get_tc_venta(db)

    sd_ventas_str = ",".join(str(x) for x in SD_VENTAS)
    df_venta_str = ",".join(str(x) for x in DF_VENTA_TODOS)
    items_excl_str = ",".join(str(x) for x in ITEMS_EXCLUIDOS)

    # ---- WHERE clauses (identical to /ranking) ----
    filter_clauses: list[str] = ["pe.activo = TRUE"]
    params: dict = {
        "stor_ids": stor_ids,
        "tc_venta": tc_venta,
    }

    if marca:
        filter_clauses.append("pe.marca = :marca")
        params["marca"] = marca

    if categoria:
        filter_clauses.append("pe.categoria = :categoria")
        params["categoria"] = categoria

    if pm == "sin_pm":
        filter_clauses.append("mp.usuario_id IS NULL")
    elif pm is not None:
        filter_clauses.append("u_pm.nombre = :pm_nombre")
        params["pm_nombre"] = pm

    if q and q.strip():
        filter_clauses.append("(pe.codigo ILIKE :q OR pe.descripcion ILIKE :q)")
        params["q"] = f"%{q.strip()}%"

    if not incluir_sin_stock:
        filter_clauses.append("COALESCE(stk.total_stock, 0) > 0")

    if not incluir_combos:
        filter_clauses.append(
            "NOT EXISTS (SELECT 1 FROM tb_item_association ia WHERE ia.item_id = pe.item_id AND ia.iasso_qty > 0)"
        )

    if solo_muerto:
        filter_clauses.append(
            f"NOT EXISTS ("
            f"SELECT 1 FROM tb_item_transactions tit_m"
            f" JOIN tb_commercial_transactions tct_m ON tct_m.ct_transaction = tit_m.ct_transaction"
            f" WHERE tit_m.item_id = pe.item_id"
            f" AND tct_m.sd_id IN ({sd_ventas_str})"
            f" AND tct_m.df_id IN ({df_venta_str})"
            f" AND tit_m.it_qty <> 0"
            f" AND tct_m.ct_date >= NOW()::date - INTERVAL '{DIAS_MUERTO_UMBRAL} days'"
            f")"
        )

    # ADR-9: scoped ranking
    scope_uid = _scope_user_id(current_user, db)
    if scope_uid is not None:
        filter_clauses.append(
            "EXISTS ("
            "SELECT 1 FROM marcas_pm mp_scope"
            " WHERE mp_scope.marca = pe.marca"
            " AND mp_scope.categoria = pe.categoria"
            " AND mp_scope.usuario_id = :scope_user_id"
            ")"
        )
        params["scope_user_id"] = scope_uid

    where_sql = " AND ".join(filter_clauses)

    # ---- Per-product CTE — exact same expressions as /ranking ----
    # Includes dias_sin_venta (last-sale LATERAL) so we can bucket "dead stock".
    # CRITICAL: all ROUND() must CAST to NUMERIC (ADR-5).
    kpis_sql = f"""
        WITH per_product AS (
            SELECT
                pe.item_id,
                -- last sale date (for dias_sin_venta + dead-stock bucket)
                ls.last_sale_date,
                CASE
                    WHEN ls.last_sale_date IS NOT NULL
                    THEN CAST(NOW()::date - ls.last_sale_date::date AS INTEGER)
                    ELSE NULL
                END                                                     AS dias_sin_venta,
                -- stock
                COALESCE(stk.total_stock, 0)                           AS total_stock,
                -- valor_costo_ars (ADR-5)
                CASE
                    WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN CASE pe.moneda_costo
                        WHEN 'USD' THEN
                            CASE WHEN :tc_venta IS NOT NULL
                            THEN ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                    * CAST(:tc_venta AS NUMERIC)
                                AS NUMERIC), 2)
                            ELSE NULL
                            END
                        ELSE
                            ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                AS NUMERIC), 2)
                        END
                    ELSE NULL
                END                                                     AS valor_costo_ars,
                -- valor_costo_usd (ADR-5)
                CASE
                    WHEN pe.costo IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN CASE pe.moneda_costo
                        WHEN 'USD' THEN
                            ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                AS NUMERIC), 2)
                        ELSE
                            CASE WHEN :tc_venta IS NOT NULL AND CAST(:tc_venta AS NUMERIC) > 0
                            THEN ROUND(
                                CAST(
                                    CAST(COALESCE(stk.total_stock, 0) AS NUMERIC)
                                    * CAST(pe.costo AS NUMERIC)
                                    / CAST(:tc_venta AS NUMERIC)
                                AS NUMERIC), 2)
                            ELSE NULL
                            END
                        END
                    ELSE NULL
                END                                                     AS valor_costo_usd,
                -- valor_venta
                CASE
                    WHEN prli.prli_price IS NOT NULL AND COALESCE(stk.total_stock, 0) > 0
                    THEN ROUND(
                        CAST(CAST(COALESCE(stk.total_stock, 0) AS NUMERIC) * prli.prli_price AS NUMERIC),
                        2
                    )
                    ELSE NULL
                END                                                     AS valor_venta
            FROM productos_erp pe
            -- last sale LATERAL (ADR-1: sd_id IN SD_VENTAS, df_id IN DF_VENTA_TODOS)
            LEFT JOIN LATERAL (
                SELECT MAX(tct.ct_date) AS last_sale_date
                FROM tb_item_transactions tit
                JOIN tb_commercial_transactions tct
                  ON tct.ct_transaction = tit.ct_transaction
                WHERE tit.item_id = pe.item_id
                  AND tct.sd_id IN ({sd_ventas_str})
                  AND tct.df_id IN ({df_venta_str})
                  AND tit.it_qty <> 0
                  AND tit.item_id NOT IN ({items_excl_str})
            ) ls ON TRUE
            -- stock across selected depots
            LEFT JOIN LATERAL (
                SELECT SUM(stock) AS total_stock
                FROM stock_por_deposito
                WHERE item_id = pe.item_id
                  AND stor_id = ANY(:stor_ids)
                  AND stock < {STOCK_SENTINEL}
            ) stk ON TRUE
            -- price list clasica
            LEFT JOIN tb_price_list_items prli
              ON prli.item_id = pe.item_id
             AND prli.prli_id = {PRLI_CLASICA}
             AND prli.comp_id = {COMP_ID}
            LEFT JOIN marcas_pm mp
              ON mp.marca = pe.marca
             AND mp.categoria = pe.categoria
            LEFT JOIN usuarios u_pm
              ON u_pm.id = mp.usuario_id
            WHERE {where_sql}
        )
        SELECT
            COUNT(DISTINCT item_id)::INTEGER                            AS total_productos,
            COALESCE(SUM(total_stock), 0)::INTEGER                     AS stock_total,
            SUM(valor_costo_ars)                                        AS capital_costo_ars,
            SUM(valor_costo_usd)                                        AS capital_costo_usd,
            SUM(valor_venta)                                            AS capital_venta_ars,
            COALESCE(
                SUM(valor_costo_ars)
                    FILTER (WHERE dias_sin_venta > 365 OR last_sale_date IS NULL),
                0)                                                      AS capital_muerto_ars,
            CASE
                WHEN SUM(valor_costo_ars) IS NOT NULL
                     AND SUM(valor_costo_ars) > 0
                THEN ROUND(
                    CAST(
                        COALESCE(SUM(valor_costo_ars)
                            FILTER (WHERE dias_sin_venta > 365 OR last_sale_date IS NULL), 0)
                        / NULLIF(SUM(valor_costo_ars), 0)
                        * 100
                    AS NUMERIC), 2)
                ELSE NULL
            END                                                         AS pct_capital_muerto
        FROM per_product
    """

    try:
        row = db.execute(text(kpis_sql), params).fetchone()
    except Exception as exc:
        logger.error("Error in consultas ranking/kpis query: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al ejecutar la consulta de KPIs",
        ) from exc

    if row is None:
        return KpisResponse(
            total_productos=0,
            stock_total=0,
            capital_costo_ars=None,
            capital_costo_usd=None,
            capital_venta_ars=None,
            capital_muerto_ars=None,
            pct_capital_muerto=None,
        )

    return KpisResponse(
        total_productos=int(row.total_productos) if row.total_productos is not None else 0,
        stock_total=int(row.stock_total) if row.stock_total is not None else 0,
        capital_costo_ars=float(row.capital_costo_ars) if row.capital_costo_ars is not None else None,
        capital_costo_usd=float(row.capital_costo_usd) if row.capital_costo_usd is not None else None,
        capital_venta_ars=float(row.capital_venta_ars) if row.capital_venta_ars is not None else None,
        capital_muerto_ars=float(row.capital_muerto_ars) if row.capital_muerto_ars is not None else None,
        pct_capital_muerto=float(row.pct_capital_muerto) if row.pct_capital_muerto is not None else None,
    )


# ---------------------------------------------------------------------------
# Facets endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/ranking/facets",
    response_model=RankingFacetsResponse,
    summary="Facets for ranking filter dropdowns",
    dependencies=[Depends(require_algun_permiso([PERMISO_RANKING_FULL, PERMISO_RANKING_PROPIO]))],
)
async def get_ranking_facets(
    marca: Optional[str] = Query(None, description="Cross-filter: narrow categorias/pms to this marca"),
    categoria: Optional[str] = Query(None, description="Cross-filter: narrow marcas/pms to this categoria"),
    pm: Optional[str] = Query(None, description="Cross-filter: narrow marcas/categorias to this PM (or 'sin_pm')"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RankingFacetsResponse:
    """Return distinct filter values for the ranking page dropdowns.

    Supports cascading/cross-filtering: each facet dimension is filtered by the
    OTHER selected dimensions (excluding itself), so selecting a PM narrows
    the available marcas+categorias, and vice versa.

    Returns:
    - marcas: filtered by categoria + pm (NOT marca itself).
    - categorias: filtered by marca + pm (NOT categoria itself).
    - pms: filtered by marca + categoria (NOT pm itself).
    - depositos: unchanged — no cross-filter applied.

    Permission required: consultas.ver_ranking o consultas.ver_mi_ranking
    """
    # ADR-9: compute scope for this user (None = full access)
    scope_uid = _scope_user_id(current_user, db)

    # ---------------------------------------------------------------------------
    # Helper: build the pm JOIN clause for productos_erp queries.
    # Returns (join_fragment, where_clause, params_to_add).
    # Only needed when pm filter is present in marcas/categorias queries.
    # ---------------------------------------------------------------------------
    def _pm_join_for_pe() -> tuple[str, str, dict]:
        """Return (JOIN fragment, WHERE clause, extra params) for pm cross-filter on pe queries."""
        join = (
            "LEFT JOIN marcas_pm mp_cf ON mp_cf.marca = pe.marca AND mp_cf.categoria = pe.categoria "
            "LEFT JOIN usuarios u_cf ON u_cf.id = mp_cf.usuario_id"
        )
        if pm == "sin_pm":
            return join, "mp_cf.usuario_id IS NULL", {}
        return join, "u_cf.nombre = :pm_nombre", {"pm_nombre": pm}

    # ---------------------------------------------------------------------------
    # Build marcas query: filter by categoria + pm (NOT by marca itself)
    # ---------------------------------------------------------------------------
    marcas_where: list[str] = [
        "pe.activo IS TRUE",
        "pe.marca IS NOT NULL",
        "pe.marca <> ''",
    ]
    marcas_joins: list[str] = []
    marcas_params: dict = {}

    if scope_uid is not None:
        marcas_where.append(
            "EXISTS (SELECT 1 FROM marcas_pm mp_scope"
            " WHERE mp_scope.marca = pe.marca"
            " AND mp_scope.categoria = pe.categoria"
            " AND mp_scope.usuario_id = :scope_user_id)"
        )
        marcas_params["scope_user_id"] = scope_uid

    if categoria:
        marcas_where.append("pe.categoria = :categoria")
        marcas_params["categoria"] = categoria

    if pm:
        join_frag, pm_clause, pm_params = _pm_join_for_pe()
        marcas_joins.append(join_frag)
        marcas_where.append(pm_clause)
        marcas_params.update(pm_params)

    marcas_join_sql = ("\n            " + "\n            ".join(marcas_joins)) if marcas_joins else ""
    marcas_where_sql = "\n              AND ".join(marcas_where)
    marcas_sql = f"""
            SELECT DISTINCT pe.marca
            FROM productos_erp pe{marcas_join_sql}
            WHERE {marcas_where_sql}
            ORDER BY pe.marca ASC
            """

    # ---------------------------------------------------------------------------
    # Build categorias query: filter by marca + pm (NOT by categoria itself)
    # ---------------------------------------------------------------------------
    cats_where: list[str] = [
        "pe.activo IS TRUE",
        "pe.categoria IS NOT NULL",
        "pe.categoria <> ''",
    ]
    cats_joins: list[str] = []
    cats_params: dict = {}

    if scope_uid is not None:
        cats_where.append(
            "EXISTS (SELECT 1 FROM marcas_pm mp_scope"
            " WHERE mp_scope.marca = pe.marca"
            " AND mp_scope.categoria = pe.categoria"
            " AND mp_scope.usuario_id = :scope_user_id)"
        )
        cats_params["scope_user_id"] = scope_uid

    if marca:
        cats_where.append("pe.marca = :marca")
        cats_params["marca"] = marca

    if pm:
        join_frag, pm_clause, pm_params = _pm_join_for_pe()
        cats_joins.append(join_frag)
        cats_where.append(pm_clause)
        cats_params.update(pm_params)

    cats_join_sql = ("\n            " + "\n            ".join(cats_joins)) if cats_joins else ""
    cats_where_sql = "\n              AND ".join(cats_where)
    cats_sql = f"""
            SELECT DISTINCT pe.categoria
            FROM productos_erp pe{cats_join_sql}
            WHERE {cats_where_sql}
            ORDER BY pe.categoria ASC
            """

    # ---------------------------------------------------------------------------
    # Build pms query: filter by marca + categoria (NOT by pm itself)
    # marcas_pm is keyed by (marca, categoria) so we filter via mp.marca / mp.categoria.
    # ---------------------------------------------------------------------------
    pms_where: list[str] = [
        "u.nombre IS NOT NULL",
        "u.nombre <> ''",
    ]
    pms_params: dict = {}

    if scope_uid is not None:
        pms_where.append("mp.usuario_id = :scope_user_id")
        pms_params["scope_user_id"] = scope_uid

    if marca:
        pms_where.append("mp.marca = :marca")
        pms_params["marca"] = marca

    if categoria:
        pms_where.append("mp.categoria = :categoria")
        pms_params["categoria"] = categoria

    pms_where_sql = "\n              AND ".join(pms_where)
    pms_sql = f"""
            SELECT DISTINCT u.nombre
            FROM marcas_pm mp
            JOIN usuarios u ON u.id = mp.usuario_id
            WHERE {pms_where_sql}
            ORDER BY u.nombre ASC
            """

    try:
        marcas_rows = db.execute(text(marcas_sql), marcas_params).fetchall()

        categorias_rows = db.execute(text(cats_sql), cats_params).fetchall()

        pms_rows = db.execute(text(pms_sql), pms_params).fetchall()

        depositos_rows = db.execute(
            text(
                """
                SELECT DISTINCT st.stor_id, s.stor_desc
                FROM tb_item_storage st
                LEFT JOIN tb_storage s
                  ON s.stor_id = st.stor_id AND s.comp_id = :comp_id
                WHERE st.stor_id IS NOT NULL
                ORDER BY st.stor_id ASC
                """
            ),
            {"comp_id": COMP_ID},
        ).fetchall()

    except Exception as exc:
        logger.error("Error in consultas ranking/facets query: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los facets de ranking",
        ) from exc

    marcas: list[str] = [row[0] for row in marcas_rows]
    categorias: list[str] = [row[0] for row in categorias_rows]
    pms: list[str] = [row[0] for row in pms_rows]
    depositos: list[DepositoFacet] = [
        DepositoFacet(
            id=row[0],
            label=row[1] if row[1] else f"Depósito {row[0]}",
        )
        for row in depositos_rows
    ]

    return RankingFacetsResponse(
        marcas=marcas,
        categorias=categorias,
        pms=pms,
        depositos=depositos,
    )
