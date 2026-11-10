"""An ML sale and its products, read from the ML sales we already store (the data Ventas ML shows), for the RMA trace.

The owner (2026-11-10): "pero en ventas ml tenemos los datos y no necesitamos al ERP para matchearlos." The sale is
found in `ml_orders_ops` by the ML order id, the pack id (every order of the pack) or the shipment id, and each of its
`ml_order_items_ops` lines is linked to its product exactly like the costing links it: the product the costing froze
(`ml_order_item_costos.producto_item_id`), else `costeo_service._productos_por_item` (MLA -> `publicaciones_ml`, else
`seller_sku` = `productos_erp.codigo`). Never a live ML call; the ERP side (order, invoice, serials, RMAs) is read by
the trace itself and only enriches this.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.producto import ProductoERP
from app.services.ml_orders_ingestion.costeo_service import _productos_por_item

# A BIGINT holds at most 19 digits; a longer value cannot name a stored order.
_MAX_DIGITOS = 18


@dataclass(frozen=True)
class ProductoVentaML:
    """One product of the sale. `item_id` is the ERP item id, 0 when the line links to no product."""

    item_id: int
    codigo: str
    descripcion: str
    cantidad: int | None


@dataclass(frozen=True)
class VentaML:
    ordenes: list[MlOrdersOps]
    productos: list[ProductoVentaML]


def _ordenes(db: Session, valor: str) -> list[MlOrdersOps]:
    if not valor.isdigit() or len(valor) > _MAX_DIGITOS:
        return []
    numero = int(valor)
    return list(
        db.scalars(
            select(MlOrdersOps)
            .where(
                or_(
                    MlOrdersOps.order_id == numero,
                    MlOrdersOps.pack_id == numero,
                    MlOrdersOps.shipping_id == numero,
                )
            )
            .order_by(MlOrdersOps.order_id)
        )
    )


def _sumar(actual: int | None, cantidad: int | None) -> int | None:
    if cantidad is None:
        return actual
    return cantidad if actual is None else actual + cantidad


def _productos(db: Session, order_ids: list[int]) -> list[ProductoVentaML]:
    lineas = list(
        db.scalars(
            select(MlOrderItemOps)
            .where(MlOrderItemOps.order_id.in_(order_ids))
            .order_by(MlOrderItemOps.order_id, MlOrderItemOps.id)
        )
    )
    if not lineas:
        return []

    congelados = {
        (row.order_id, row.item_id, row.variation_id): row.producto_item_id
        for row in db.execute(
            select(
                MlOrderItemCosto.order_id,
                MlOrderItemCosto.item_id,
                MlOrderItemCosto.variation_id,
                MlOrderItemCosto.producto_item_id,
            ).where(MlOrderItemCosto.order_id.in_(order_ids))
        )
    }
    sin_congelar = [linea for linea in lineas if (linea.order_id, linea.item_id, linea.variation_id) not in congelados]
    resueltos = _productos_por_item(db, sin_congelar)
    vinculo_vivo = {id(sin_congelar[idx]): producto for idx, (producto, _fuente) in resueltos.items()}

    ids_congelados = set(congelados.values())
    productos_congelados = (
        {p.item_id: p for p in db.scalars(select(ProductoERP).where(ProductoERP.item_id.in_(sorted(ids_congelados))))}
        if ids_congelados
        else {}
    )

    productos: dict[object, ProductoVentaML] = {}
    for linea in lineas:
        congelado = congelados.get((linea.order_id, linea.item_id, linea.variation_id))
        producto = productos_congelados.get(congelado) if congelado is not None else vinculo_vivo.get(id(linea))
        if producto is not None:
            clave: object = producto.item_id
            nuevo = ProductoVentaML(
                item_id=producto.item_id,
                codigo=producto.codigo or linea.seller_sku or linea.item_id,
                descripcion=producto.descripcion or linea.title or linea.item_id,
                cantidad=linea.quantity,
            )
        elif congelado is not None:
            # Frozen to a product the ERP catalog no longer lists: keep the link, describe it from the ML line.
            clave = congelado
            nuevo = ProductoVentaML(
                item_id=congelado,
                codigo=linea.seller_sku or linea.item_id,
                descripcion=linea.title or linea.item_id,
                cantidad=linea.quantity,
            )
        else:
            clave = ("ml", linea.item_id, linea.variation_id)
            nuevo = ProductoVentaML(
                item_id=0,
                codigo=linea.seller_sku or linea.item_id,
                descripcion=linea.title or linea.item_id,
                cantidad=linea.quantity,
            )
        previo = productos.get(clave)
        productos[clave] = (
            nuevo
            if previo is None
            else ProductoVentaML(
                item_id=previo.item_id,
                codigo=previo.codigo,
                descripcion=previo.descripcion,
                cantidad=_sumar(previo.cantidad, linea.quantity),
            )
        )
    return list(productos.values())


def buscar_venta_ml(db: Session, valor: str) -> VentaML | None:
    """The stored ML sale the typed value names (order, pack or shipment id), or None when we never stored it."""
    ordenes = _ordenes(db, valor.strip())
    if not ordenes:
        return None
    return VentaML(ordenes=ordenes, productos=_productos(db, [o.order_id for o in ordenes]))
