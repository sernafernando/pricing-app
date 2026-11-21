"""Real 30D c/ SO: the Board's sold lines with their sell out, as every Publicaciones ML view shows them
(sell-in-costo-si T3 PR 5, D1).

Owner L12: "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional, si de ganancia tenés
1000 y le agregás 10% tenés 1100 de ganancia". The cost of a sale is costo SI, which already holds every invoice sell
in and the brand loyalty, so the Board's sell in figures (`sell_in`, `m_sell_in`, `sell_in_lineas`: FIFO lots and
cost bonuses) are never read here: they neither come off the cost nor add to the profit. The sell out is added to
the profit, over the plain cost:

    Total Gauss c/ SO = tg + sell_out              markup c/ SO = (mtg + m_sell_out) / costo

A figure applies only where some sold line has a sell out (None otherwise, never a copy of the plain one: each view
falls back to the plain figure itself, as it did). It reads a Board `Row`, a summed row with the same field names,
or (`markup_so_sql`) the columns of a summed Board subquery.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, case
from sqlalchemy.sql.elements import ColumnElement

from app.services.ml_daily_metrics import board


def applies(r: Any) -> bool:
    """Some sold line of the row has a sell out."""
    return bool(getattr(r, "sell_out_lineas", None))


def total_gauss_so(r: Any) -> Optional[Decimal]:
    if not applies(r) or r.sell_out is None:
        return None
    return r.tg + r.sell_out


def markup_so(r: Any) -> Optional[Decimal]:
    """In percentage points, like `board.markup_of`; None where it does not apply or the sell out is unknown."""
    if not applies(r) or r.m_sell_out is None:
        return None
    return board.markup_of(r.mtg + r.m_sell_out, r.costo)


def markup_so_sql(c: Any) -> ColumnElement:
    """`markup_so` over the columns `c` of a summed Board row (`mtg`, `costo`, `m_sell_out`, `sell_out_lineas`):
    NULL where it does not apply, so those rows sort last both ways."""
    return case(
        (and_(c.sell_out_lineas > 0, c.costo > 0), (c.mtg + c.m_sell_out) * 100 / c.costo),
        else_=None,
    )
