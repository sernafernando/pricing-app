"""The Sell in "Productos" list: one row per product whose active purchase lines still have units (read only).

Each row carries the cost mode governing today (None: FIFO, the default), the units its lines have left, what the
next sale takes per unit and the date of its latest line. Everything comes from the costing's own batched reads
(`lotes`, `unidades_usadas`, `vigentes`, `periodos`), so the number of queries does not grow with the products and
the values are the ones the lot viewer (`visor_lotes`) shows for each product.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_in import SellInCompra, SellInCompraItem
from app.services.sell_in.costing import get_costing, reemplazados


@dataclass(frozen=True)
class ProductoCosto:
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    modo: Optional[str]  # the mode governing today; None: FIFO, the default
    unidades: int  # the units its lines have left, counting from today or later
    sell_in_unit: Optional[Decimal]  # ARS the next sale takes per unit; None: no line counts today
    ultima_compra: date  # the date its latest line counts from


def productos(db: Session, hoy: date) -> List[ProductoCosto]:
    """The products with units left in active purchase lines, by description then code."""
    costing = get_costing()
    ids = [
        item_id
        for (item_id,) in db.query(SellInCompraItem.item_id)
        .join(SellInCompra, SellInCompra.id == SellInCompraItem.compra_id)
        .filter(SellInCompra.estado == "activa")
        .distinct()
    ]
    lotes = costing.lotes(db, ids)
    usadas = costing.unidades_usadas(db, [x.compra_item_id for item in lotes.values() for x in item])
    # The lots a manual block replaced have no units left (the lot viewer's count).
    restantes = {
        item_id: sum(max(x.cantidad - usadas.get(x.compra_item_id, 0), 0) for x in item[reemplazados(item, hoy) :])
        for item_id, item in lotes.items()
    }
    con_unidades = sorted(item_id for item_id, unidades in restantes.items() if unidades > 0)
    if not con_unidades:
        return []
    vigentes = costing.vigentes(db, con_unidades, hoy)
    periodos = costing.periodos(db, con_unidades)
    datos = {
        p.item_id: (p.codigo, p.descripcion)
        for p in db.query(ProductoERP.item_id, ProductoERP.codigo, ProductoERP.descripcion).filter(
            ProductoERP.item_id.in_(con_unidades)
        )
    }
    filas = []
    for item_id in con_unidades:
        # `periodos` comes oldest first: the last one started by today governs.
        modo = next((p.modo for p in reversed(periodos.get(item_id, [])) if p.desde <= hoy), None)
        vigente = vigentes.get(item_id)
        codigo, descripcion = datos.get(item_id, (None, None))
        filas.append(
            ProductoCosto(
                item_id=item_id,
                codigo=codigo,
                descripcion=descripcion,
                modo=modo,
                unidades=restantes[item_id],
                sell_in_unit=vigente.descuento_unit_ars if vigente is not None else None,
                # A manual block is no purchase; every listed product has a purchase line.
                ultima_compra=max(x.fecha for x in lotes[item_id] if x.modo_id is None),
            )
        )
    return sorted(filas, key=lambda x: ((x.descripcion or "").lower(), x.codigo or "", x.item_id))
