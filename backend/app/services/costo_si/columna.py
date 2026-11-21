"""The costo SI column next to the list cost (sell-in-costo-si T3 PR 2, inventory §10, the PPP companion pattern C4):
the page reads `lote.actuales` once and shows each product's `payload`. Display only: it changes no other number.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import literal_column

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


def costo_ars_sql(item: str, tipo_cambio: Optional[float]):
    """The current cost in pesos of the SQL expression `item` at the caller's USD rate (None: the latest), as a scalar
    SQL expression: exactly `lote.actuales(...)[item].costo_ars`, NULL when unknown. For an ORDER BY that must match
    the numbers a page computes in Python over that reader (Tienda's Gremio / Sugerido sort, T3 PR 6)."""
    tc = repr(float(tipo_cambio)) if tipo_cambio else "NULL"
    return literal_column(f"(SELECT csi_cs.costo_si_ars FROM ({lote.sql_actual_fila(item, tc)}) csi_cs)")


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
