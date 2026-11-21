"""Reading a product's costo SI (S10, S11): the value in force on a date and its breakdown.

A combo (not a PC) has no history of its own: its costo SI is the sum of its components' costo SI x their quantity in
the combo ("el x2 es el costo de una unidad x la cantidad", L4.9); unknown when any component has none, or when they
are in different currencies (each product's costo SI is in its own cost currency, L18: use `lote` for a value in pesos).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

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
    "moneda",
)


@dataclass
class Componente:
    item_id: int
    cantidad: Decimal
    costo_si_usd: Optional[Decimal]
    moneda: Optional[str] = None


@dataclass
class CostoSi:
    item_id: int
    fecha: date
    es_combo: bool
    costo_si_usd: Optional[Decimal]  # in `moneda` (the name predates L18)
    vigente_desde: Optional[date]
    moneda: Optional[str] = None
    pasos: List[dict] = field(default_factory=list)
    componentes: List[Componente] = field(default_factory=list)


def _vigente(db: Session, item_id: int, fecha: date) -> tuple[Optional[Decimal], Optional[date], Optional[str]]:
    row = db.execute(
        select(P.promedio_usd, P.fecha, P.moneda)
        .where(P.item_id == item_id, P.fecha <= fecha)
        .order_by(P.fecha.desc(), P.orden.desc())
        .limit(1)
    ).first()
    return (row[0], row[1], row[2]) if row else (None, None, None)


def vigente(db: Session, item_id: int, fecha: date) -> tuple[Optional[Decimal], Optional[date]]:
    """The average in force on `fecha` (the last step dated on or before it), in the step's `moneda`."""
    valor, desde, _ = _vigente(db, item_id, fecha)
    return valor, desde


def leer(db: Session, item_id: int, fecha: date) -> CostoSi:
    if fuentes.es_combo(db, item_id):
        partes = db.execute(
            text("SELECT componente_item_id, cantidad FROM combo_componentes WHERE combo_item_id = :i ORDER BY 1"),
            {"i": item_id},
        ).all()
        componentes = []
        for c, q in partes:
            valor, _, moneda = _vigente(db, c, fecha)
            componentes.append(Componente(c, Decimal(q), valor, moneda))
        monedas = {c.moneda for c in componentes}
        known = componentes and all(c.costo_si_usd is not None for c in componentes) and len(monedas) == 1
        total = redondear(sum((c.costo_si_usd * c.cantidad for c in componentes), Decimal(0))) if known else None
        return CostoSi(item_id, fecha, True, total, None, monedas.pop() if known else None, componentes=componentes)
    valor, desde, moneda = _vigente(db, item_id, fecha)
    pasos = [
        dict(r._mapping)
        for r in db.execute(select(*(getattr(P, c) for c in _COLUMNAS)).where(P.item_id == item_id).order_by(P.orden))
    ]
    return CostoSi(item_id, fecha, False, valor, desde, moneda, pasos=pasos)
