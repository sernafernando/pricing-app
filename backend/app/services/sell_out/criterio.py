"""A `monto_total` campaign split by a criterion (tactical monto total, S2/S3): `SellOutCampana.reparto_criterio`.

- `iguales`: the same fixed share for every product of the campaign's reach.
- `costo`: fixed shares proportional to each product's cost, `productos_erp.costo` converted to the campaign currency
  (a USD cost in an ARS campaign, or the other way round, at the campaign's own rate when it has one, else the
  latest BNA `venta`); a product without a cost gets no share.
- `unidades`: no stored share; the allocator spreads the total over every unit sold of the reach in the dates
  (`reparto.repartir_por_unidades`), so it follows sales and returns.

The fixed shares come from `app.services.sell_in.split.split` (`por_unidad` with one unit per product for equal
parts, `proporcional` with the cost as weight): cent-exact, the remainder on the heaviest product, so they add up
exactly to the total. A negative total (a deduction) is split by its absolute value and negated.

`vista_previa` computes the same result without storing anything, for the panel's preview: the fixed shares, or for
`unidades` what the allocator would credit each product now (by its net units sold in the dates so far), always in
the campaign currency as loaded (before any VAT is taken off).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana
from app.models.tipo_cambio import TipoCambio
from app.services.sell_in.compras import SellInError, costo_en_moneda, moneda
from app.services.sell_in.split import Line, SellInSplitError, split
from app.services.sell_out import alcance, asignacion, reparto

IGUALES, UNIDADES, COSTO = "iguales", reparto.UNIDADES, "costo"
CRITERIOS = (IGUALES, UNIDADES, COSTO)
FIJOS = (IGUALES, COSTO)


class CriterioError(ValueError):
    """The campaign cannot be split by that criterion; the message is for the operator, in Spanish."""


def _alcance(db: Session, campana: SellOutCampana) -> List[int]:
    return sorted(alcance.productos(db, [campana.id]).get(campana.id, {}))


def _tasa(campana: SellOutCampana, db: Session) -> Optional[Decimal]:
    if campana.tipo_cambio is not None:
        return Decimal(campana.tipo_cambio)
    fila = (
        db.query(TipoCambio.venta)
        .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0)
        .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
        .first()
    )
    return Decimal(str(fila[0])) if fila else None


def _costos(db: Session, campana: SellOutCampana, item_ids: List[int]) -> Dict[int, Decimal]:
    """Each product's cost in the campaign currency; 0 without a cost (it then gets no share)."""
    tasa = _tasa(campana, db)
    salida = {}
    rows = db.query(ProductoERP.item_id, ProductoERP.costo, ProductoERP.moneda_costo).filter(
        ProductoERP.item_id.in_(item_ids)
    )
    for item_id, costo, moneda_costo in rows:
        if costo is None or costo <= 0:
            salida[item_id] = Decimal(0)
            continue
        try:
            salida[item_id] = costo_en_moneda(Decimal(str(costo)), moneda(moneda_costo), campana.moneda, tasa)
        except SellInError as exc:
            raise CriterioError(
                "No hay tipo de cambio para pasar los costos a la moneda de la campaña: no se puede repartir por costo"
            ) from exc
    return salida


def cuotas(db: Session, campana: SellOutCampana, criterio: str) -> Dict[int, Decimal]:
    """`{item_id: fixed share}` of an `iguales` or `costo` split over the campaign's reach, adding up to its total;
    products whose share is 0 (no cost, or a total of a few cents over many products) are left out."""
    item_ids = _alcance(db, campana)
    if not item_ids:
        raise CriterioError("La campaña no alcanza ningún producto: no hay entre quiénes repartir")
    total = Decimal(campana.monto_total)
    if criterio == IGUALES:
        formula, lineas = "por_unidad", [Line(i, 1, Decimal(0)) for i in item_ids]
    else:
        costos = _costos(db, campana, item_ids)
        if not any(costos.values()):
            raise CriterioError("Ningún producto de la campaña tiene costo cargado: no se puede repartir por costo")
        formula, lineas = "proporcional", [Line(i, 1, costos.get(i, Decimal(0))) for i in item_ids]
    try:
        montos = split(formula, abs(total), lineas)
    except SellInSplitError as exc:
        raise CriterioError(str(exc)) from exc
    signo = -1 if total < 0 else 1
    return {linea.item_id: signo * m for linea, m in zip(lineas, montos) if m}


def _por_unidades(db: Session, campana: SellOutCampana) -> Tuple[Dict[int, int], Dict[int, Decimal]]:
    """`({item_id: net units}, {item_id: amount})` the allocator would write now if the campaign were split by
    units, as loaded (no VAT taken off). Reads, never writes."""
    previa = SellOutCampana(
        **{col.key: getattr(campana, col.key) for col in SellOutCampana.__table__.columns},
    )
    previa.reparto_criterio, previa.monto_incluye_iva = UNIDADES, False
    filas = asignacion.filas_de(db, previa)
    unidades: Dict[int, int] = {}
    montos: Dict[int, Decimal] = {}
    for x in filas:
        unidades[x.item_id] = unidades.get(x.item_id, 0) + x.unidades
        montos[x.item_id] = montos.get(x.item_id, Decimal("0.00")) + x.monto
    return unidades, montos


def vista_previa(db: Session, campana: SellOutCampana, criterio: str) -> dict:
    """What splitting the campaign by `criterio` gives, per product of its reach, without storing anything."""
    if campana.tipo != "monto_total":
        raise CriterioError("Solo las campañas por monto total se reparten por producto")
    unidades, montos = _por_unidades(db, campana)
    if criterio in FIJOS:
        montos = cuotas(db, campana, criterio)
    item_ids = _alcance(db, campana)
    codigos = dict(db.query(ProductoERP.item_id, ProductoERP.codigo).filter(ProductoERP.item_id.in_(item_ids)))
    items = [
        {
            "item_id": i,
            "codigo": codigos.get(i),
            "unidades": unidades.get(i, 0),
            "monto": montos.get(i, Decimal("0.00")),
        }
        for i in item_ids
    ]
    total = reparto.cents(Decimal(campana.monto_total))
    return {
        "criterio": criterio,
        "moneda": campana.moneda,
        "monto_total": total,
        "items": items,
        "sin_asignar": total - sum((x["monto"] for x in items), Decimal("0.00")),
    }
