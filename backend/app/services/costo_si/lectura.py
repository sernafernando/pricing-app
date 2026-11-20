"""Reading a product's costo SI (S10, S11): the value in force on a date and its breakdown.

A combo (not a PC) has no history of its own: its costo SI is the sum of its components' costo SI x their quantity in
the combo ("el x2 es el costo de una unidad x la cantidad", L4.9); unknown when any component has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.costo_si import CostoSiNcSinAsignar
from app.models.costo_si import CostoSiPaso as P
from app.services.costo_si import fuentes
from app.services.costo_si.engine import redondear

_COLUMNAS = (
    "orden",
    "tipo",
    "fecha",
    "ct_transaction",
    "cantidad",
    "costo_neto_usd",
    "sell_ins",
    "sell_in_pct",
    "costo_neto_neto_usd",
    "stock_antes",
    "stock_base",
    "stock_despues",
    "promedio_usd",
    "tipo_cambio",
    "fuente_tc",
    "en_compras",
)


@dataclass
class Componente:
    item_id: int
    cantidad: Decimal
    costo_si_usd: Optional[Decimal]


@dataclass
class CostoSi:
    item_id: int
    fecha: date
    es_combo: bool
    costo_si_usd: Optional[Decimal]
    vigente_desde: Optional[date]
    pasos: List[dict] = field(default_factory=list)
    componentes: List[Componente] = field(default_factory=list)
    nc_sin_asignar: List[dict] = field(default_factory=list)  # supplier NCs not tied to one invoice (owner L5)


def vigente(db: Session, item_id: int, fecha: date) -> tuple[Optional[Decimal], Optional[date]]:
    """The average in force on `fecha` (the last step dated on or before it)."""
    row = db.execute(
        select(P.promedio_usd, P.fecha)
        .where(P.item_id == item_id, P.fecha <= fecha)
        .order_by(P.fecha.desc(), P.orden.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def leer(db: Session, item_id: int, fecha: date) -> CostoSi:
    if fuentes.es_combo(db, item_id):
        partes = db.execute(
            text("SELECT componente_item_id, cantidad FROM combo_componentes WHERE combo_item_id = :i ORDER BY 1"),
            {"i": item_id},
        ).all()
        componentes = [Componente(c, Decimal(q), vigente(db, c, fecha)[0]) for c, q in partes]
        known = componentes and all(c.costo_si_usd is not None for c in componentes)
        total = redondear(sum((c.costo_si_usd * c.cantidad for c in componentes), Decimal(0))) if known else None
        return CostoSi(item_id, fecha, True, total, None, componentes=componentes)
    valor, desde = vigente(db, item_id, fecha)
    pasos = [
        dict(r._mapping)
        for r in db.execute(select(*(getattr(P, c) for c in _COLUMNAS)).where(P.item_id == item_id).order_by(P.orden))
    ]
    N = CostoSiNcSinAsignar
    ncs = [
        dict(r._mapping)
        for r in db.execute(
            select(N.nc_ct, N.fecha, N.importe, N.curr_id, N.motivo)
            .where(N.item_id == item_id)
            .order_by(N.fecha, N.nc_ct)
        )
    ]
    return CostoSi(item_id, fecha, False, valor, desde, pasos=pasos, nc_sin_asignar=ncs)
