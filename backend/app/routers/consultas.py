"""
Router: Consultas — product ranking.

Endpoint: GET /api/consultas/ranking

Returns a paginated, sortable ranking of products aggregated from ERP data.
Each row contains:
  - Calculated ageing (days since last SALE, using tb_item_transactions ⋈
    tb_commercial_transactions with the canonical sale definition confirmed
    in ADR-1: sd_id IN SD_VENTAS, df_id IN DF_VENTA_TODOS).
  - Last purchase data (puco_id=10, latest it_cd).
  - Sales velocity over ventana_dias.
  - Stock total across selected depots (itst_cant).
  - Monetary valuations in BOTH ARS and USD (valor_costo_ars, valor_costo_usd).
  - valor_venta in ARS (price list clasica prli_id=4).
  - ERP-sourced ageing from productos_ageing (LEFT JOIN — null at launch).

Permission gate: consultas.ver_ranking  (seeded by Alembic migration M1).
No JWT → 401 | Wrong permission → 403.

ADR references:
  ADR-1: Canonical sale definition.
  ADR-4: ventana_dias parameter.
  ADR-5: Dual-currency cost columns (ARS + USD); FX via TipoCambio.venta.
  ADR-7: Dynamic multi-column sort via SORT_COLUMNS whitelist.
  ADR-8: incluir_sin_stock / incluir_combos filter params.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.consultas import (
    SORT_COLUMNS_PERMITIDAS,
    VENTANA_DIAS_PERMITIDAS,
    DepositoFacet,
    RankingFacetsResponse,
    RankingItemRow,
    RankingResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/consultas", tags=["consultas"])

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


# ---------------------------------------------------------------------------
# Dynamic sort column map (ADR-7)
# ---------------------------------------------------------------------------

# Maps the public sort key → SQL expression fragment used in ORDER BY.
# All expressions reference aliases defined in the CTE / subquery below.
_SORT_EXPR_MAP: dict[str, str] = {
    "dias_sin_venta": "dias_sin_venta",
    "unidades_vendidas_ventana": "unidades_vendidas_ventana",
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
    {"dias_sin_venta", "last_purchase_date", "valor_costo_ars", "valor_costo_usd", "valor_venta"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_nulls_clause(sort_key: str, sort_dir: str) -> str:
    """Return 'NULLS LAST' or 'NULLS FIRST' depending on column and direction.

    Per ADR-7: nullable ranking columns always sort NULLS LAST so that products
    with data appear before products without data, regardless of sort direction.
    """
    if sort_key in _NULLS_LAST_COLS:
        return "NULLS LAST"
    # Non-nullable computed columns: standard PostgreSQL behaviour
    return "NULLS LAST" if sort_dir == "desc" else "NULLS FIRST"


def _parse_sort_params(sort_params: list[str]) -> list[tuple[str, str, str]]:
    """Parse and validate multi-sort params of the form 'campo:asc|desc'.

    Returns a deduped, ordered list of (campo, sql_expr, direction) tuples.
    Raises HTTPException 422 on invalid field or direction.
    """
    result: list[tuple[str, str, str]] = []
    seen_fields: set[str] = set()
    for entry in sort_params:
        parts = entry.split(":", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Formato de sort inválido: '{entry}'. Use 'campo:asc' o 'campo:desc'.",
            )
        campo, direccion = parts[0].strip(), parts[1].strip().lower()
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
    dependencies=[Depends(require_permiso("consultas.ver_ranking"))],
)
async def get_ranking(
    # Pagination
    page: int = Query(default=1, ge=1, description="Página (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Filas por página (max 200)"),
    # Multi-column sort: repeated param, each 'campo:asc|desc' (ADR-7)
    sort: list[str] = Query(
        default=["dias_sin_venta:desc"],
        description="Orden multi-columna. Cada valor: 'campo:asc|desc'. Se aplican en orden.",
    ),
    # Filters
    marca: Optional[str] = Query(default=None, max_length=100),
    categoria: Optional[str] = Query(default=None, max_length=100),
    pm: Optional[str] = Query(
        default=None,
        description="Nombre del PM asignado, o 'sin_pm' para productos sin PM",
    ),
    stor_ids: list[int] = Query(default=[1], description="IDs de depósito"),
    ventana_dias: int = Query(default=90, description="Ventana de ventas en días {30,60,90,180}"),
    # Boolean filters (ADR-8)
    incluir_sin_stock: bool = Query(
        default=False,
        description="Si True, incluye productos sin stock en los depósitos seleccionados.",
    ),
    incluir_combos: bool = Query(
        default=False,
        description="Si True, incluye combos/producción (productos padre en tb_item_association).",
    ),
    # Auth + permission are enforced by the require_permiso(...) route dependency above.
    db: Session = Depends(get_db),
) -> RankingResponse:
    """Product ranking ordered by sales ageing and configurable metrics.

    Aggregates ERP transaction data to compute:
    - dias_sin_venta: days since last sale across all channels.
    - unidades_vendidas_ventana: units sold in the configured window.
    - total_stock: sum of itst_cant for selected depots.
    - valor_costo_ars: stock × costo in ARS (FX applied when origin is USD).
    - valor_costo_usd: stock × costo in USD (FX applied when origin is ARS).
    - valor_venta: total_stock × precio from tb_price_list_items (prli_id=4) in ARS.
    - erp_ageing_dias: ERP-computed ageing from productos_ageing (null at launch).

    Multi-sort: `sort` param accepts repeated 'campo:asc|desc' entries applied in order.
    Boolean filters: incluir_sin_stock (default False), incluir_combos (default False).

    Permission required: consultas.ver_ranking
    """
    # Validate ventana_dias
    if ventana_dias not in VENTANA_DIAS_PERMITIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ventana_dias {ventana_dias} no es válido. Opciones: {sorted(VENTANA_DIAS_PERMITIDAS)}",
        )

    # Parse and validate multi-sort params (raises 422 on bad input).
    # Each tuple carries (campo, sql_expr, direction) so the NULLS clause never
    # misaligns even if duplicate fields are sent.
    sort_tuples = _parse_sort_params(sort)

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
        "ventana_dias_interval": f"{ventana_dias} days",
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

    # incluir_sin_stock=False → only rows with stock > 0 in selected depots (ADR-8)
    if not incluir_sin_stock:
        filter_clauses.append("COALESCE(stk.total_stock, 0) > 0")

    # incluir_combos=False → exclude products that are parents in tb_item_association (ADR-8)
    if not incluir_combos:
        filter_clauses.append(
            "NOT EXISTS (SELECT 1 FROM tb_item_association ia WHERE ia.item_id = pe.item_id AND ia.iasso_qty > 0)"
        )

    where_sql = " AND ".join(filter_clauses)

    # ---- Main query ----
    # Two LATERALs:
    #   ls — last_sale: MAX(ct_date) over all channels, SUM(it_qty) FILTER window
    #   lp — last_purchase: most recent purchase row (puco_id=10)
    # Stock: SUM(itst_cant) WHERE stor_id = ANY(:stor_ids)
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
            END                                                AS valor_venta,
            -- units sold in window
            COALESCE(ls.unidades_ventana, 0)                  AS unidades_vendidas_ventana
        FROM productos_erp pe
        -- LATERAL: last sale + units in window
        LEFT JOIN LATERAL (
            SELECT
                MAX(tct.ct_date)                              AS last_sale_date,
                SUM(
                    CASE
                        WHEN tct.ct_date >= NOW() - CAST(:ventana_dias_interval AS INTERVAL)
                        THEN ABS(tit.it_qty)
                        ELSE 0
                    END
                )                                             AS unidades_ventana
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
            SELECT SUM(itst_cant) AS total_stock
            FROM tb_item_storage
            WHERE item_id = pe.item_id
              AND stor_id = ANY(:stor_ids)
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
            SELECT SUM(itst_cant) AS total_stock
            FROM tb_item_storage
            WHERE item_id = pe.item_id
              AND stor_id = ANY(:stor_ids)
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
            unidades_vendidas_ventana=int(row.unidades_vendidas_ventana)
            if row.unidades_vendidas_ventana is not None
            else 0,
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
# Facets endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/ranking/facets",
    response_model=RankingFacetsResponse,
    summary="Facets for ranking filter dropdowns",
    dependencies=[Depends(require_permiso("consultas.ver_ranking"))],
)
async def get_ranking_facets(
    db: Session = Depends(get_db),
) -> RankingFacetsResponse:
    """Return distinct filter values for the ranking page dropdowns.

    Returns:
    - marcas: DISTINCT productos_erp.marca WHERE activo IS TRUE, non-null, sorted asc.
    - categorias: DISTINCT productos_erp.categoria WHERE activo IS TRUE, non-null, sorted asc.
    - pms: DISTINCT usuarios.nombre via marcas_pm JOIN, non-null, sorted asc.
      Matches the PM display name produced by the ranking endpoint
      (expression: u_pm.nombre — the same column used in the pm filter).
    - depositos: DISTINCT tb_item_storage.stor_id + stor_desc as DepositoFacet{id, label}, sorted asc.
      label = stor_desc if available, else "Depósito {id}".

    Permission required: consultas.ver_ranking
    """
    try:
        marcas_rows = db.execute(
            text(
                """
                SELECT DISTINCT marca
                FROM productos_erp
                WHERE activo IS TRUE
                  AND marca IS NOT NULL
                  AND marca <> ''
                ORDER BY marca ASC
                """
            )
        ).fetchall()

        categorias_rows = db.execute(
            text(
                """
                SELECT DISTINCT categoria
                FROM productos_erp
                WHERE activo IS TRUE
                  AND categoria IS NOT NULL
                  AND categoria <> ''
                ORDER BY categoria ASC
                """
            )
        ).fetchall()

        pms_rows = db.execute(
            text(
                """
                SELECT DISTINCT u.nombre
                FROM marcas_pm mp
                JOIN usuarios u ON u.id = mp.usuario_id
                WHERE u.nombre IS NOT NULL
                  AND u.nombre <> ''
                ORDER BY u.nombre ASC
                """
            )
        ).fetchall()

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
