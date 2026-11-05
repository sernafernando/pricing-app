"""Read model for Gestión Full: one row per (ERP product, MLAU).

Joins Publicaciones ML product links to ERP stock, Full replenishment sales
windows, Colecta+Flex units from Ventas ML sale lines, last Full inbound
(Target), and optional PM overrides.

Row key: (producto_item_id, user_product_id). inventory_id is still selected
(one Código ML per MLAU via DISTINCT ON) for display and Target/override joins.

Sugerido = min(max(0, target - stock_full), stock_erp): replenish toward last
inbound, never above ERP stock. Null when Target is missing.

Filters (defaults match envio-workflow-decisions D1 / D1b / D1c):
  full_mode=en|fuera|todos — en Full = stock_full>0 OR ventas_full_30d>0
  include_zero_stock — when false, hide stock_erp=0/null
  marcas / categorias — multi-select, case-insensitive (same contract as
  ProductFiltersPanel / product_facets)
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.product_facets import (
    ComboRow,
    ProductFacetOptions,
    ProductSelection,
    product_facet_options,
)

FullMode = Literal["en", "fuera", "todos"]

_VALID_FULL_MODES = frozenset({"en", "fuera", "todos"})

_FILTER_SQL = """
    AND (
      :include_zero_stock = 1
      OR COALESCE(p.stock, 0) > 0
    )
    AND (
      :full_mode = 'todos'
      OR (
        :full_mode = 'en'
        AND (
          COALESCE(st.full_quantity, 0) > 0
          OR COALESCE(r.units_30d, 0) > 0
        )
      )
      OR (
        :full_mode = 'fuera'
        AND COALESCE(st.full_quantity, 0) = 0
        AND COALESCE(r.units_30d, 0) = 0
      )
    )
"""

# Multi-select product filters (case-insensitive). Empty selection = no filter.
_PRODUCT_FILTER_SQL = """
    AND (
      :has_marcas = 0
      OR upper(p.marca) = ANY(:marcas_upper)
    )
    AND (
      :has_categorias = 0
      OR upper(p.categoria) = ANY(:categorias_upper)
    )
    AND (
      :has_pms = 0
      OR EXISTS (
        SELECT 1
        FROM marcas_pm mpm
        WHERE mpm.usuario_id = ANY(:pms)
          AND upper(mpm.marca) = upper(p.marca)
          AND upper(mpm.categoria) = upper(p.categoria)
      )
    )
"""

# Planificación: only rows with an active PM Listo freeze.
_LISTO_FILTER_SQL = """
    AND (
      :solo_listo = 0
      OR ready.producto_item_id IS NOT NULL
    )
"""

_LINKED_CTE = """
    linked AS (
      SELECT DISTINCT ON (l.producto_item_id, i.user_product_id)
        l.producto_item_id,
        i.inventory_id,
        i.user_product_id,
        i.item_id AS mla,
        i.family_id
      FROM ml_item_product_links l
      JOIN ml_items i ON i.item_id = l.item_id
      WHERE l.producto_item_id IS NOT NULL
        AND l.variation_id = 0
        AND i.inventory_id IS NOT NULL
        AND i.user_product_id IS NOT NULL
        AND i.never_existed IS NOT TRUE
        AND i.gone_at IS NULL
      ORDER BY l.producto_item_id, i.user_product_id, i.inventory_id, i.item_id
    )
"""

# family_id is exact (bigint as text): partial ILIKE would false-match other families.
_Q_SQL = """
    WHERE (
      :q = '' OR
      p.codigo ILIKE '%' || :q || '%' OR
      p.descripcion ILIKE '%' || :q || '%' OR
      linked.inventory_id ILIKE '%' || :q || '%' OR
      COALESCE(linked.user_product_id, '') ILIKE '%' || :q || '%' OR
      (
        linked.family_id IS NOT NULL
        AND CAST(linked.family_id AS TEXT) = :q
      )
    )
"""


def _sugerido(
    target: Optional[int],
    stock_full: Optional[int],
    stock_erp: Optional[int] = None,
) -> Optional[int]:
    """Units to replenish toward Target, capped by ERP stock (P9)."""
    if target is None:
        return None
    raw = max(0, int(target) - int(stock_full or 0))
    return min(raw, max(0, int(stock_erp or 0)))


def _normalize_full_mode(full_mode: str) -> FullMode:
    mode = (full_mode or "en").strip().lower()
    if mode not in _VALID_FULL_MODES:
        return "en"
    return mode  # type: ignore[return-value]


def _normalize_labels(values: Sequence[str] | None) -> list[str]:
    """Trim, drop blanks, de-dupe case-insensitively (first spelling wins)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = (raw or "").strip()
        if not value:
            continue
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


_LIST_SQL = text(
    f"""
    WITH {_LINKED_CTE},
    colecta_flex AS (
      SELECT
        lines.product AS producto_item_id,
        COALESCE(
          SUM(lines.qty) FILTER (WHERE lines.day >= (CURRENT_DATE - INTERVAL '7 days')),
          0
        )::int AS ventas_colecta_flex_7d,
        COALESCE(SUM(lines.qty), 0)::int AS ventas_colecta_flex_30d
      FROM ml_sale_lines lines
      JOIN ml_orders_ops o ON o.order_id = lines.order_id
      JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
      WHERE lines.day >= (CURRENT_DATE - INTERVAL '30 days')
        AND s.logistic_type IN ('self_service', 'cross_docking')
      GROUP BY lines.product
    )
    SELECT
      p.item_id AS producto_item_id,
      p.codigo AS ean,
      p.descripcion,
      p.marca,
      p.categoria,
      p.stock AS stock_erp,
      linked.inventory_id,
      linked.user_product_id,
      linked.mla,
      st.full_quantity AS stock_full,
      r.units_7d AS ventas_full_7d,
      r.units_14d AS ventas_full_14d,
      r.units_21d AS ventas_full_21d,
      r.units_30d AS ventas_full_30d,
      cf.ventas_colecta_flex_7d,
      cf.ventas_colecta_flex_30d,
      inbound.cantidad AS target,
      o.cantidad AS override,
      caja.unidades AS unidades_por_caja,
      ready.qty_pm AS qty_pm,
      (ready.producto_item_id IS NOT NULL) AS pm_ready
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_user_product_replenishment r ON r.user_product_id = linked.user_product_id
    LEFT JOIN colecta_flex cf ON cf.producto_item_id = linked.producto_item_id
    LEFT JOIN ml_fulfillment_last_inbound inbound ON inbound.inventory_id = linked.inventory_id
    LEFT JOIN gestion_full_override o ON o.inventory_id = linked.inventory_id
    LEFT JOIN gestion_full_unidades_caja caja ON caja.producto_item_id = linked.producto_item_id
    LEFT JOIN gestion_full_pm_ready ready
      ON ready.producto_item_id = linked.producto_item_id
     AND ready.user_product_id = linked.user_product_id
    {_Q_SQL}
    {_PRODUCT_FILTER_SQL}
    {_FILTER_SQL}
    {_LISTO_FILTER_SQL}
    ORDER BY p.codigo ASC, linked.user_product_id ASC
    LIMIT :limit OFFSET :offset
    """
)

_COUNT_SQL = text(
    f"""
    WITH {_LINKED_CTE}
    SELECT COUNT(*)::int AS total
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_user_product_replenishment r ON r.user_product_id = linked.user_product_id
    LEFT JOIN gestion_full_pm_ready ready
      ON ready.producto_item_id = linked.producto_item_id
     AND ready.user_product_id = linked.user_product_id
    {_Q_SQL}
    {_PRODUCT_FILTER_SQL}
    {_FILTER_SQL}
    {_LISTO_FILTER_SQL}
    """
)

# Distinct (marca, categoría, PM) under non-product filters — product_facet_options
# applies marca/categoría/PM selection with skip-own cross-filtering in memory.
_FACET_PAIRS_SQL = text(
    f"""
    WITH {_LINKED_CTE}
    SELECT DISTINCT p.marca, p.categoria, mpm.usuario_id, u.nombre
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_user_product_replenishment r ON r.user_product_id = linked.user_product_id
    LEFT JOIN gestion_full_pm_ready ready
      ON ready.producto_item_id = linked.producto_item_id
     AND ready.user_product_id = linked.user_product_id
    LEFT JOIN marcas_pm mpm
      ON upper(mpm.marca) = upper(p.marca)
     AND upper(mpm.categoria) = upper(p.categoria)
    LEFT JOIN usuarios u ON u.id = mpm.usuario_id
    {_Q_SQL}
    {_FILTER_SQL}
    {_LISTO_FILTER_SQL}
    """
)


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        "producto_item_id": row.producto_item_id,
        "ean": row.ean,
        "descripcion": row.descripcion,
        "marca": row.marca,
        "categoria": row.categoria,
        "inventory_id": row.inventory_id,
        "user_product_id": row.user_product_id,
        "mla": row.mla,
        "stock_erp": row.stock_erp,
        "stock_full": row.stock_full,
        "ventas_full_7d": row.ventas_full_7d,
        "ventas_full_14d": row.ventas_full_14d,
        "ventas_full_21d": row.ventas_full_21d,
        "ventas_full_30d": row.ventas_full_30d,
        "ventas_colecta_flex_7d": getattr(row, "ventas_colecta_flex_7d", None),
        "ventas_colecta_flex_30d": getattr(row, "ventas_colecta_flex_30d", None),
        "target": getattr(row, "target", None),
        "sugerido": _sugerido(
            getattr(row, "target", None),
            getattr(row, "stock_full", None),
            getattr(row, "stock_erp", None),
        ),
        "override": getattr(row, "override", None),
        "unidades_por_caja": getattr(row, "unidades_por_caja", None),
        "qty_pm": getattr(row, "qty_pm", None),
        "pm_ready": bool(getattr(row, "pm_ready", False)),
        "puede_editar_override": False,
    }


def _base_params(
    *,
    q: str,
    full_mode: str,
    include_zero_stock: bool,
    solo_listo: bool = False,
) -> dict[str, Any]:
    return {
        "q": (q or "").strip(),
        "full_mode": _normalize_full_mode(full_mode),
        "include_zero_stock": 1 if include_zero_stock else 0,
        "solo_listo": 1 if solo_listo else 0,
    }


def _product_filter_params(
    marcas: Sequence[str] | None,
    categorias: Sequence[str] | None,
    pms: Sequence[int] | None = None,
) -> dict[str, Any]:
    marcas_norm = _normalize_labels(marcas)
    categorias_norm = _normalize_labels(categorias)
    pms_norm: list[int] = []
    seen_pm: set[int] = set()
    for raw in pms or ():
        pid = int(raw)
        if pid in seen_pm:
            continue
        seen_pm.add(pid)
        pms_norm.append(pid)
    return {
        "has_marcas": 1 if marcas_norm else 0,
        "has_categorias": 1 if categorias_norm else 0,
        "has_pms": 1 if pms_norm else 0,
        "marcas_upper": [m.upper() for m in marcas_norm],
        "categorias_upper": [c.upper() for c in categorias_norm],
        "pms": pms_norm,
        "marcas": marcas_norm,
        "categorias": categorias_norm,
    }


def _empty_product_facets() -> dict[str, Any]:
    return ProductFacetOptions().model_dump()


def _build_product_facets(
    db: Session,
    *,
    q: str,
    full_mode: str,
    include_zero_stock: bool,
    solo_listo: bool,
    marcas: Sequence[str],
    categorias: Sequence[str],
    pms: Sequence[int],
) -> dict[str, Any]:
    """Cross-filtered marca/categoría/PM lists for ProductFiltersPanel."""
    facet_params = _base_params(
        q=q,
        full_mode=full_mode,
        include_zero_stock=include_zero_stock,
        solo_listo=solo_listo,
    )
    pairs = db.execute(_FACET_PAIRS_SQL, facet_params).all()
    rows = [
        ComboRow(
            marca=marca,
            categoria=categoria,
            subcategoria_id=None,
            subcategoria_nombre=None,
            subcategoria_categoria=None,
            pm_id=pm_id,
            pm_nombre=pm_nombre,
        )
        for marca, categoria, pm_id, pm_nombre in pairs
    ]
    selection = ProductSelection(
        marcas=tuple(marcas),
        categorias=tuple(categorias),
        pms=tuple(pms),
    )
    return product_facet_options(db, rows, selection).model_dump()


def list_gestion_full(
    db: Session,
    *,
    q: str = "",
    marcas: Sequence[str] | None = None,
    categorias: Sequence[str] | None = None,
    pms: Sequence[int] | None = None,
    full_mode: str = "en",
    include_zero_stock: bool = False,
    solo_listo: bool = False,
    include_facets: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated Gestión Full rows ordered by EAN then MLAU (groups stay contiguous).

    `include_facets=False` skips the DISTINCT pairs query (e.g. Planificación
    refresh after Listo/Desbloquear when the panel options are already loaded).
    """
    product = _product_filter_params(marcas, categorias, pms)
    params = {
        **_base_params(
            q=q,
            full_mode=full_mode,
            include_zero_stock=include_zero_stock,
            solo_listo=solo_listo,
        ),
        "has_marcas": product["has_marcas"],
        "has_categorias": product["has_categorias"],
        "has_pms": product["has_pms"],
        "marcas_upper": product["marcas_upper"],
        "categorias_upper": product["categorias_upper"],
        "pms": product["pms"],
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }
    total: Optional[int] = db.execute(_COUNT_SQL, params).scalar()
    rows = db.execute(_LIST_SQL, params).mappings().all()
    if include_facets:
        facets_product = _build_product_facets(
            db,
            q=q,
            full_mode=full_mode,
            include_zero_stock=include_zero_stock,
            solo_listo=solo_listo,
            marcas=product["marcas"],
            categorias=product["categorias"],
            pms=product["pms"],
        )
    else:
        facets_product = _empty_product_facets()
    return {
        "total": int(total or 0),
        "limit": params["limit"],
        "offset": params["offset"],
        "items": [_row_dict(r) for r in rows],
        "facets": {"product": facets_product or _empty_product_facets()},
    }
