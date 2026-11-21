"""The lines Productos draws under a product's cost, for the Costo cell of Publicaciones ML (publication, detail
and product rows): the PPP, the cost with sell in, and the costo SI (sell-in-costo-si T3 PR 2, display only).

Its own module because the sell in resolver is a catalog read (`productos_sell_in_out`), opened in this package only
to the view extraction modules (`tests/services/ml_publications/test_resources.py`); the listing reaches it through
here, as `view/detail.py` does for one publication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.sell_in_out_producto import SellInOutProducto
from app.services.costo_ppp_service import PppMarkups, resolver_ppp_batch
from app.services.costo_si import columna, lote
from app.services.ml_publications.view.markup import PublicationMarkup, UnitMarkup, summarize
from app.services.ml_publications.view.markup_inputs import product_ivas
from app.services.ml_publications.view.markup_service import ItemMarkup
from app.services.pricing_calculator import calcular_markup, obtener_tipo_cambio_actual
from app.services.productos_sell_in_out import resolver_sell_in_out_batch, resolver_sell_in_out_por_contexto
from app.services.sell_out import alcance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CostedProduct:
    """What `SellInOutBatch.markups` reads of a product: its cost in its own currency and its VAT."""

    item_id: int
    costo: Optional[float]
    moneda_costo: str
    iva: Optional[float]


NO_COST_LINES: dict[str, Any] = {"ppp": None, "sell_in_out": None, "costo_si": None}


def cost_lines(
    pricing_db: Session, products: Mapping[int, tuple[Any, Any, Any]]
) -> Optional[dict[int, dict[str, Any]]]:
    """The two lines Productos draws under a product's cost, per product id of `products` (id -> cost, currency,
    VAT): `ppp` (`resolver_ppp_batch` + `PppMarkups`, null without a qualifying row) and `sell_in_out`
    (`resolver_sell_in_out_batch`, null when neither applies), and `costo_si` (`lote.actuales` + `columna.payload`,
    the list cost with fuente 'lista' without a costo SI, null without any cost). No markup is recorded: the cost
    cell shows none. Every resolver reads the pricing database, once for the whole page.

    None when one of those reads fails (a database error, logged): the lines are informative, so the page answers as it did before they
    existed, each row with its cost and without the line keys, instead of failing whole. The reads run in a
    savepoint, so a failed one leaves the session usable for the rest of the request."""
    if not products:
        return {}
    try:
        with pricing_db.begin_nested():
            return _cost_lines(pricing_db, products)
    except SQLAlchemyError:  # a failed read; a programming error still surfaces
        logger.exception("Publicaciones ML: no se pudieron armar las líneas de PPP / sell in del costo")
        return None


def cost_lines_by_publication(pricing_db: Session, rows: Sequence[Any]) -> Optional[dict[str, dict[str, Any]]]:
    """Like `cost_lines`, per publication (`row.item_id`, its MLA): two publications of the same product on different
    official stores each get the tactical companions that reach their store. The store is the publication's
    `mlp_official_store_id` (`alcance.stores_por_mla`), the one the sell out and sell in allocators credit its sales
    under, so the row shows what the money would be; a publication without one is `("ml", None)`, which every
    all-stores tactical reaches. Every store of the page is resolved from ONE read (`resolver_sell_in_out_por_contexto`),
    PPP, the costo SI and the rate once. None when a read fails, as `cost_lines`."""
    linked = [r for r in rows if getattr(r, "producto_item_id", None)]
    if not linked:
        return {}
    try:
        with pricing_db.begin_nested():
            stores = alcance.stores_por_mla(pricing_db, {str(r.item_id) for r in linked})
            products = {r.producto_item_id: (r.costo, r.moneda_costo, r.costo_iva) for r in linked}
            store_of = {str(r.item_id): stores.get(str(r.item_id)) for r in linked}
            contextos = {store: [("ml", store)] for store in set(store_of.values())}
            ids = sorted(products)
            batches = resolver_sell_in_out_por_contexto(pricing_db, ids, date.today(), contextos)
            ppp = resolver_ppp_batch(pricing_db, ids)
            rate = obtener_tipo_cambio_actual(pricing_db, "USD")
            costos = lote.actuales(pricing_db, ids, tipo_cambio=rate)
            return {
                str(r.item_id): _lines(
                    r.producto_item_id, products, ppp, batches[store_of[str(r.item_id)]], rate, costos
                )
                for r in linked
            }
    except SQLAlchemyError:
        logger.exception("Publicaciones ML: no se pudieron armar las líneas de PPP / sell in del costo")
        return None


def _cost_lines(pricing_db: Session, products: Mapping[int, tuple[Any, Any, Any]]) -> dict[int, dict[str, Any]]:
    ids = sorted(products)
    ppp = resolver_ppp_batch(pricing_db, ids)
    sell_in_out = resolver_sell_in_out_batch(pricing_db, ids, date.today())
    rate = obtener_tipo_cambio_actual(pricing_db, "USD")
    costos = lote.actuales(pricing_db, ids, tipo_cambio=rate)
    return {item_id: _lines(item_id, products, ppp, sell_in_out, rate, costos) for item_id in ids}


def _lines(
    item_id: int, products: Mapping[int, tuple[Any, Any, Any]], ppp, sell_in_out, rate, costos
) -> dict[str, Any]:
    costo, moneda, iva = products[item_id]
    moneda = getattr(moneda, "value", moneda) or "ARS"
    ppp_payload = PppMarkups(ppp.get(item_id), moneda_costo=moneda, tipo_cambio=rate).payload()
    product = _CostedProduct(item_id, _as_float(costo), moneda, _as_float(iva))
    sio_payload = sell_in_out.markups(product, tipo_cambio=rate).payload()
    costo_si = columna.payload(costos.get(item_id))
    return {
        "ppp": None if ppp_payload is None else ppp_payload.model_dump(),
        "sell_in_out": None if sio_payload is None else sio_payload.model_dump(),
        "costo_si": None if costo_si is None else costo_si.model_dump(),
    }


def _as_float(value: Any) -> Optional[float]:
    """A Numeric column's value (a Decimal) as the float the sell in arithmetic mixes it with."""
    return None if value is None else float(value)


# --- Markup actual c/ SISO (pubml-markup-siso S1, S2) ------------------------------------------------------------

REASON_SISO_PENDIENTE = "siso_pendiente"  # the unit's sell in / sell out has no amount (a missing rate or base)
_SISO_KEY = "unidad"


@dataclass(frozen=True)
class SisoMarkup:
    """A publication's markup with sell in / sell out: `markup` is its units summarized with the plain markup's rule
    (`summarize`: range, worst variation), so `markup_service.aggregate_nodes` and `product_markup` read it as they
    read the plain one; `pending` counts the units without a value because their sell in / sell out could not be
    priced, `applies` whether any unit has one."""

    markup: PublicationMarkup
    pending: int
    applies: bool

    def as_item(self, plain: ItemMarkup) -> ItemMarkup:
        """`plain` with this markup in place of its own (its units' products kept), for the node aggregations."""
        return replace(plain, markup=self.markup, ads=None)


@dataclass(frozen=True)
class _PricedUnit:
    """What `SellInOutBatch.markups` reads of the product a unit prices: its cost already in pesos (`costo_ars`), as
    the panel's Resumen passes it (`detail._PricedProduct`)."""

    item_id: int
    costo: float
    iva: Optional[float]
    moneda_costo: str = "ARS"


def siso_unit_value(
    unit: UnitMarkup, payload: Optional[SellInOutProducto], key: str
) -> tuple[Optional[float], bool, bool]:
    """`(value, applies, pending)` of one priced unit, the panel's rule (`SellInOutMarkup`): with sell in and sell out,
    else with sell in alone (a pending sell out included), else pending when an amount could not be priced; where
    neither applies, the plain markup of the unit's net over its cost (before Ads, as the panel and Precios)."""
    if payload is not None:
        value = payload.markups_sell_in_out.get(key, payload.markups_sell_in.get(key))
        if value is not None:
            return value, True, False
        sin_costo = payload.sell_in is not None and payload.sell_in.costo is None
        sin_credito = payload.sell_out is not None and payload.sell_out.monto_unit is None
        if sin_costo or sin_credito:
            return None, True, True
    return round(calcular_markup(unit.limpio, unit.costo_ars) * 100, 2), False, False


def siso_markups(pricing_db: Session, items: Mapping[str, ItemMarkup]) -> Optional[dict[str, SisoMarkup]]:
    """The markup with sell in / sell out of each publication of `items` (`compute_markups`' result): every priced
    unit at today's price with what the panel's Resumen gives its product (`resolver_sell_in_out_por_contexto`, the
    publication's official store as the allocators credit it), ONE resolver read for the whole set plus one read of
    the products' VAT. None when a read fails (logged), as `cost_lines`: the column is then empty, the page answers."""
    if not items:
        return {}
    try:
        with pricing_db.begin_nested():
            return _siso_markups(pricing_db, items)
    except SQLAlchemyError:  # a failed read; a programming error still surfaces
        logger.exception("Publicaciones ML: no se pudo calcular el markup con sell in / sell out")
        return None


def _siso_markups(pricing_db: Session, items: Mapping[str, ItemMarkup]) -> dict[str, SisoMarkup]:
    products = sorted(
        {p for item in items.values() for p, unit in _units(item) if p is not None and unit.limpio is not None}
    )
    iva = product_ivas(pricing_db, products)
    stores = alcance.stores_por_mla(pricing_db, set(items))
    contextos = {store: [("ml", store)] for store in {stores.get(mla) for mla in items}}
    batches = resolver_sell_in_out_por_contexto(pricing_db, products, date.today(), contextos)
    return {mla: _siso_of(item, batches[stores.get(mla)], iva) for mla, item in items.items()}


def _units(item: ItemMarkup) -> list[tuple[Optional[int], UnitMarkup]]:
    """Each unit of the publication with its linked product (`ItemMarkup.unit_products`; none when they disagree)."""
    units = item.markup.variations
    products = item.unit_products if len(item.unit_products) == len(units) else (None,) * len(units)
    return list(zip(products, units))


def _siso_of(item: ItemMarkup, batch: Any, iva: Mapping[int, Optional[float]]) -> SisoMarkup:
    units: list[UnitMarkup] = []
    pending, applies = 0, False
    for product, unit in _units(item):
        if product is None or unit.limpio is None or unit.costo_ars is None:
            units.append(unit if unit.value is None else replace(unit, value=None))
            continue
        accumulator = batch.markups(_PricedUnit(product, unit.costo_ars, iva.get(product)), precio_lista_ml=unit.price)
        accumulator.record(_SISO_KEY, unit.limpio)
        value, applied, waiting = siso_unit_value(unit, accumulator.payload(), _SISO_KEY)
        applies = applies or applied
        pending += waiting
        units.append(replace(unit, value=value, reason=REASON_SISO_PENDIENTE if waiting else unit.reason))
    return SisoMarkup(summarize(units), pending, applies)
