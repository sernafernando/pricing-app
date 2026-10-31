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
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

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


_LIST_SQL = text(
    f"""
    WITH linked AS (
      SELECT DISTINCT ON (l.producto_item_id, i.user_product_id)
        l.producto_item_id,
        i.inventory_id,
        i.user_product_id,
        i.item_id AS mla
      FROM ml_item_product_links l
      JOIN ml_items i ON i.item_id = l.item_id
      WHERE l.producto_item_id IS NOT NULL
        AND l.variation_id = 0
        AND i.inventory_id IS NOT NULL
        AND i.user_product_id IS NOT NULL
        AND i.never_existed IS NOT TRUE
        AND i.gone_at IS NULL
      ORDER BY l.producto_item_id, i.user_product_id, i.inventory_id, i.item_id
    ),
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
      o.cantidad AS override
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_user_product_replenishment r ON r.user_product_id = linked.user_product_id
    LEFT JOIN colecta_flex cf ON cf.producto_item_id = linked.producto_item_id
    LEFT JOIN ml_fulfillment_last_inbound inbound ON inbound.inventory_id = linked.inventory_id
    LEFT JOIN gestion_full_override o ON o.inventory_id = linked.inventory_id
    WHERE (
      :q = '' OR
      p.codigo ILIKE '%' || :q || '%' OR
      p.descripcion ILIKE '%' || :q || '%' OR
      linked.inventory_id ILIKE '%' || :q || '%' OR
      COALESCE(linked.user_product_id, '') ILIKE '%' || :q || '%'
    )
    AND (:marca = '' OR p.marca = :marca)
    AND (:categoria = '' OR p.categoria = :categoria)
    {_FILTER_SQL}
    ORDER BY p.codigo ASC, linked.user_product_id ASC
    LIMIT :limit OFFSET :offset
    """
)

_COUNT_SQL = text(
    f"""
    WITH linked AS (
      SELECT DISTINCT ON (l.producto_item_id, i.user_product_id)
        l.producto_item_id,
        i.inventory_id,
        i.user_product_id
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
    SELECT COUNT(*)::int AS total
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_user_product_replenishment r ON r.user_product_id = linked.user_product_id
    WHERE (
      :q = '' OR
      p.codigo ILIKE '%' || :q || '%' OR
      p.descripcion ILIKE '%' || :q || '%' OR
      linked.inventory_id ILIKE '%' || :q || '%' OR
      COALESCE(linked.user_product_id, '') ILIKE '%' || :q || '%'
    )
    AND (:marca = '' OR p.marca = :marca)
    AND (:categoria = '' OR p.categoria = :categoria)
    {_FILTER_SQL}
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
        "puede_editar_override": False,
    }


def list_gestion_full(
    db: Session,
    *,
    q: str = "",
    marca: str = "",
    categoria: str = "",
    full_mode: str = "en",
    include_zero_stock: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated Gestión Full rows ordered by EAN then MLAU (groups stay contiguous)."""
    params = {
        "q": (q or "").strip(),
        "marca": (marca or "").strip(),
        "categoria": (categoria or "").strip(),
        "full_mode": _normalize_full_mode(full_mode),
        "include_zero_stock": 1 if include_zero_stock else 0,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }
    total: Optional[int] = db.execute(_COUNT_SQL, params).scalar()
    rows = db.execute(_LIST_SQL, params).mappings().all()
    return {
        "total": int(total or 0),
        "limit": params["limit"],
        "offset": params["offset"],
        "items": [_row_dict(r) for r in rows],
    }
