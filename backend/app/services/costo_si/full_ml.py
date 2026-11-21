"""Full stock for costo SI: Mercado Libre's, never GBP depot 17's balance (S3, owner L8: "el depósito de full no es el
stock de full, el stock de full lo traemos de ml, y ese podés calcular para atrás dependiendo las ventas de full"),
rebuilt from what the app already stores (owner L11: "tenemos tanto el stock actual de full como las ventas de full de
los últimos días"). No Mercado Libre call.

The product's Full is the Full of its own publications' inventories: the item's inventory when linked at item level,
the variation's own user product when linked per variation (ML keeps one inventory per variation; the Auditoría's
photo counts it the same way). Combos' publications are not the product's (S11, L7.1). A past instant `t` is walked back from the nearest ML reading after it:

- the Auditoría's daily photo (`producto_stock_diario.stock_full`, ML's Full that morning: `stock.snapshot` takes it
  at 06:00 local), the first one at or after `t`; else today's ML stock (`ml_user_product_stock.full_quantity`);
- plus the Full sales between `t` and that reading (`ml_orders_ops` / `ml_order_items_ops`, shipment
  `logistic_type = 'fulfillment'`, not cancelled), which had not left Full yet at `t`;
- minus the shipments into Full recorded between them (GBP's remitos into depot 17, `sd_id` 102), which had not
  arrived yet at `t`. Depot 17's balance and its other movements are never read.

Anchoring on the daily photo, not only on today, keeps a shipment ML already received but GBP has not remitted yet
(RE200, 2026-11-20: +200 the same afternoon) out of the past days. ML-side returns and adjustments into Full are not
stored by the app: they show up only from the next photo on.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
HORA_FOTO = time(6, 0)  # `stock.snapshot.run_at_local`: when the day's ML Full is read
DEPOSITO_FULL = 17
SD_REMITO = 102  # GBP "02.Remito / Guía de Despacho": the shipment of our units into Full

_INVENTARIOS_SQL = text("""
    SELECT DISTINCT ON (i.inventory_id) i.inventory_id, i.user_product_id
    FROM ml_item_product_links l
    JOIN ml_items i ON i.item_id = l.item_id
    WHERE l.producto_item_id = :i AND l.variation_id = 0 AND i.inventory_id IS NOT NULL
    ORDER BY i.inventory_id, i.user_product_id
""")

# Variations linked to the product: ML's inventory is the variation's user product; the item has none.
_VARIACIONES_SQL = text("""
    SELECT l.item_id, l.variation_id, v.user_product_id
    FROM ml_item_product_links l
    LEFT JOIN ml_item_variations v ON v.item_id = l.item_id AND v.variation_id = l.variation_id
    WHERE l.producto_item_id = :i AND l.variation_id <> 0
    ORDER BY l.item_id, l.variation_id
""")

_ACTUAL_SQL = text(
    "SELECT COALESCE(sum(full_quantity), 0) FROM ml_user_product_stock WHERE user_product_id = ANY(CAST(:ups AS text[]))"
)

# The first daily photo at or after :t, with the instant it was read (06:00 local of its day).
_FOTO_SQL = text("""
    SELECT stock_full, instante FROM (
        SELECT stock_full, (fecha + CAST(:hora AS time)) AT TIME ZONE :zona AS instante
        FROM producto_stock_diario WHERE item_id = :i
    ) fotos
    WHERE instante >= :t
    ORDER BY instante LIMIT 1
""")

_VENTAS_SQL = text("""
    SELECT COALESCE(sum(oi.quantity), 0)
    FROM ml_order_items_ops oi
    JOIN ml_orders_ops o ON o.order_id = oi.order_id
    JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
    WHERE (oi.item_id IN (SELECT item_id FROM ml_items WHERE inventory_id = ANY(CAST(:invs AS text[])))
           OR (oi.item_id, oi.variation_id) IN (
               SELECT * FROM unnest(CAST(:v_items AS text[]), CAST(:v_ids AS bigint[]))))
      AND s.logistic_type = 'fulfillment' AND o.status <> 'cancelled'
      AND o.date_created >= :t AND (CAST(:hasta AS timestamptz) IS NULL OR o.date_created < :hasta)
""")

# GBP stores naive local time: the bounds come in as naive local too.
_REMITOS_SQL = text("""
    SELECT COALESCE(sum(it.it_qty), 0)
    FROM tb_item_transactions it
    JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction AND ct.sd_id = :sd
    WHERE it.item_id = :i AND it.stor_id = :d
      AND it.it_cd >= :t AND (CAST(:hasta AS timestamp) IS NULL OR it.it_cd < :hasta)
""")


def inventarios(db: Session, item_id: int) -> List[Tuple[str, Optional[str]]]:
    return [(r[0], r[1]) for r in db.execute(_INVENTARIOS_SQL, {"i": item_id})]


def variaciones(db: Session, item_id: int) -> List[Tuple[str, int, Optional[str]]]:
    return [(r[0], int(r[1]), r[2]) for r in db.execute(_VARIACIONES_SQL, {"i": item_id})]


def _local(t: Optional[datetime]) -> Optional[datetime]:
    return None if t is None else t.astimezone(ZONA).replace(tzinfo=None)


def full_disponible(db: Session, item_id: int, t: datetime) -> int:
    """The product's Full available stock at instant `t` (aware), walked back from the next ML reading (module
    docstring). 0 when none of its own publications or variations is linked to an ML inventory."""
    invs = inventarios(db, item_id)
    vars_ = variaciones(db, item_id)
    if not invs and not vars_:
        return 0
    foto = db.execute(_FOTO_SQL, {"i": item_id, "t": t, "hora": HORA_FOTO, "zona": str(ZONA)}).first()
    if foto is not None:
        base, hasta = int(foto[0]), foto[1]
    else:
        ups = sorted({up for _, up in invs if up is not None} | {up for _, _, up in vars_ if up is not None})
        base, hasta = int(db.execute(_ACTUAL_SQL, {"ups": ups}).scalar() or 0), None
    vendidas = db.execute(
        _VENTAS_SQL,
        {
            "invs": [inv for inv, _ in invs],
            "v_items": [m for m, _, _ in vars_],
            "v_ids": [v for _, v, _ in vars_],
            "t": t,
            "hasta": hasta,
        },
    ).scalar()
    remitidas = db.execute(
        _REMITOS_SQL,
        {"i": item_id, "d": DEPOSITO_FULL, "sd": SD_REMITO, "t": _local(t), "hasta": _local(hasta)},
    ).scalar()
    return base + int(vendidas or 0) - int(remitidas or 0)
