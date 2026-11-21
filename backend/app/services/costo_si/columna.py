"""The costo SI column next to the list cost (sell-in-costo-si T3 PR 2, inventory §10, the PPP companion pattern C4):
read for a page, then one accumulator per product records each markup site with that site's `limpio`.

Display only: it changes no other number, so a failure to read it never fails the screen (the column is just absent).
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional

from sqlalchemy import literal_column
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.costo_si import CostoSiPayload
from app.services.costo_si import lote
from app.services.costo_si.lote import Costo
from app.services.pricing_calculator import calcular_markup

logger = logging.getLogger(__name__)


def leer(db: Session, item_ids: Iterable[int], *, tipo_cambio=None) -> Dict[int, Costo]:
    """`lote.actuales` for a screen (`tipo_cambio`: the rate the screen's own markups use). Its SQL is Postgres only:
    elsewhere, or when the read fails (inside a savepoint, so the caller's transaction survives), nothing."""
    ids = list(item_ids)
    if not ids or db.get_bind().dialect.name != "postgresql":
        return {}
    try:
        with db.begin_nested():
            return lote.actuales(db, ids, tipo_cambio=tipo_cambio)
    except SQLAlchemyError:
        logger.exception("costo SI column could not be read for %d products", len(ids))
        return {}


def orden(item: str):
    """The `costo_si` sort key: the current costo SI in pesos of the SQL expression `item`, so USD and ARS costs
    compare as money (null without a cost or without a rate, last like a missing cost)."""
    return literal_column(f"({lote.sql_actual(item)})")


def _float(valor) -> Optional[float]:
    return None if valor is None else float(valor)


class CostoSiMarkups:
    """One product's costo SI payload and its markups. `record` mirrors `PppMarkups.record`: same keys, same `limpio`,
    same scaling, with the cost in pesos; a no-op without pesos. `payload` is None when the cost is unknown."""

    def __init__(self, costo: Optional[Costo]) -> None:
        self._costo = costo if costo is not None and costo.costo is not None else None
        ars = self._costo.costo_ars if self._costo else None
        self._ars = float(ars) if ars is not None and ars > 0 else None
        self._markups: dict[str, float] = {}

    def record(self, key: str, limpio: float, *, percent: bool = True) -> None:
        if self._ars is None or limpio is None:
            return
        raw = calcular_markup(limpio, self._ars)
        self._markups[key] = round(raw * 100, 2) if percent else raw

    def payload(self) -> Optional[CostoSiPayload]:
        c = self._costo
        if c is None:
            return None
        return CostoSiPayload(
            costo=float(c.costo),
            moneda=c.moneda,
            fuente=c.fuente,
            desde=c.costo_si_desde,
            tipo_cambio=_float(c.tipo_cambio),
            costo_ars=_float(c.costo_ars),
            markups=dict(self._markups),
        )
