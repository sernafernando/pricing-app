"""The costo SI column next to the list cost (sell-in-costo-si T3 PR 2, inventory §10, the PPP companion pattern C4):
the page reads `lote.actuales` once and shows each product's `payload`. Display only: it changes no other number.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Numeric, column, literal_column, text

from app.schemas.costo_si import CostoSiPayload
from app.services.costo_si import lote
from app.services.costo_si.lote import Costo


def orden(item: str):
    """The `costo_si` sort key: the current costo SI in pesos of the SQL expression `item`, so USD and ARS costs
    compare as money (null without a cost or without a rate, last like a missing cost)."""
    return literal_column(f"({lote.sql_actual(item)})")


def orden_catalogo(item: str):
    """`orden` for a list with many rows per product (Publicaciones ML): each product's costo SI is computed once per
    query, not once per row (`lote.sql_actual_catalogo`, measured on prod in #2366)."""
    return literal_column(lote.sql_actual_catalogo(item))


def costos_ars_conjunto(tipo_cambio: Optional[float]):
    """Every product's current cost in pesos at the caller's USD rate (None: the latest), for an ORDER BY that must
    match the numbers a page computes in Python over `lote.actuales` (Tienda's Gremio / Sugerido sort, T3 PR 6):
    ONE set-based read of the reader (`lote.sql_actual_conjunto`), as a subquery with `item_id` and `costo_si_ars`
    (NULL when unknown), at most one row per `item_id`, to LEFT JOIN on it. Timed on prod: a correlated subquery per
    row and per use made the sort ~4x slower than this."""
    tc = repr(float(tipo_cambio)) if tipo_cambio else "NULL"
    conjunto = lote.sql_actual_conjunto("SELECT item_id FROM productos_erp", tc)
    return (
        text(f"SELECT csi_all.item_id, csi_all.costo_si_ars FROM ({conjunto}) csi_all")
        .columns(column("item_id", Integer), column("costo_si_ars", Numeric))
        .subquery("csi_tienda")
    )


def _float(valor) -> Optional[float]:
    return None if valor is None else float(valor)


def payload(c: Optional[Costo]) -> Optional[CostoSiPayload]:
    """One product's costo SI payload, None when its cost is unknown. No markups of its own: the main markups are
    already over this cost in pesos (S13, #2363), so a copy would be the same numbers twice (T3 PR 3)."""
    if c is None or c.costo is None:
        return None
    return CostoSiPayload(
        costo=float(c.costo),
        moneda=c.moneda,
        fuente=c.fuente,
        desde=c.costo_si_desde,
        tipo_cambio=_float(c.tipo_cambio),
        tipo_cambio_fecha=c.tipo_cambio_fecha,
        costo_ars=_float(c.costo_ars),
    )
