"""A product's sell-in cost modes (owner: "Para sell in vamos a mantener el FIFO pero además quiero un sistema que con
un permiso aparte se pueda elegir ponderar el stock y el precio y no usar solo fifo [...]").

`sell_in_modos_producto` holds append-only rows, one per change of a product's mode from `desde` on. No row means
FIFO, the default. The row that governs a date is the latest with `desde <= date`; two rows on the same `desde` are
ordered by id, so the one saved last wins. Design: handoffs `sell-in-costos-propuesta.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.sell_in import SellInModoProducto
from app.models.usuario import Usuario


@dataclass(frozen=True)
class ModoProducto:
    id: int
    modo: str
    desde: date
    cantidad: Optional[int]
    costo_unit: Optional[Decimal]
    costo_base_unit: Optional[Decimal]
    origen: str
    compra_id: Optional[int]
    usuario_id: int
    usuario_nombre: Optional[str]
    created_at: datetime


def historial(db: Session, item_id: int) -> List[ModoProducto]:
    """The product's mode rows, the one that starts last first (same `desde`: the one saved last first)."""
    m = SellInModoProducto
    filas = (
        db.query(m, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == m.usuario_id)
        .filter(m.item_id == item_id)
        .order_by(m.desde.desc(), m.id.desc())
    )
    return [
        ModoProducto(
            id=fila.id,
            modo=fila.modo,
            desde=fila.desde,
            cantidad=fila.cantidad,
            costo_unit=fila.costo_unit,
            costo_base_unit=fila.costo_base_unit,
            origen=fila.origen,
            compra_id=fila.compra_id,
            usuario_id=fila.usuario_id,
            usuario_nombre=nombre,
            created_at=fila.created_at,
        )
        for fila, nombre in filas
    ]


def vigente(filas: List[ModoProducto], dia: date) -> Optional[ModoProducto]:
    """The row governing `dia` from `historial`'s rows (newest first); None: FIFO."""
    return next((fila for fila in filas if fila.desde <= dia), None)
