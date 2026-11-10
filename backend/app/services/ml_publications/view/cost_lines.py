"""The two lines Productos draws under a product's cost, for the Costo cell of Publicaciones ML (publication, detail
and product rows): the PPP and the cost with sell in.

Its own module because the sell in resolver is a catalog read (`productos_sell_in_out`), opened in this package only
to the view extraction modules (`tests/services/ml_publications/test_resources.py`); the listing reaches it through
here, as `view/detail.py` does for one publication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.costo_ppp_service import PppMarkups, resolver_ppp_batch
from app.services.pricing_calculator import obtener_tipo_cambio_actual
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


NO_COST_LINES: dict[str, Any] = {"ppp": None, "sell_in_out": None}


def cost_lines(
    pricing_db: Session, products: Mapping[int, tuple[Any, Any, Any]]
) -> Optional[dict[int, dict[str, Any]]]:
    """The two lines Productos draws under a product's cost, per product id of `products` (id -> cost, currency,
    VAT): `ppp` (`resolver_ppp_batch` + `PppMarkups`, null without a qualifying row) and `sell_in_out`
    (`resolver_sell_in_out_batch`, null when neither applies). No markup is recorded: the cost cell shows neither.
    Both resolvers read the pricing database, once for the whole page.

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
    `mlp_official_store_id` (`alcance._stores_por_mla`), the one the sell out and sell in allocators credit its sales
    under, so the row shows what the money would be; a publication without one is `("ml", None)`, which every
    all-stores tactical reaches. Every store of the page is resolved from ONE read (`resolver_sell_in_out_por_contexto`),
    PPP and the rate once. None when a read fails, as `cost_lines`."""
    linked = [r for r in rows if getattr(r, "producto_item_id", None)]
    if not linked:
        return {}
    try:
        with pricing_db.begin_nested():
            stores = alcance._stores_por_mla(pricing_db, {str(r.item_id) for r in linked})
            products = {r.producto_item_id: (r.costo, r.moneda_costo, r.costo_iva) for r in linked}
            store_of = {str(r.item_id): stores.get(str(r.item_id)) for r in linked}
            contextos = {store: [("ml", store)] for store in set(store_of.values())}
            ids = sorted(products)
            batches = resolver_sell_in_out_por_contexto(pricing_db, ids, date.today(), contextos)
            ppp = resolver_ppp_batch(pricing_db, ids)
            rate = obtener_tipo_cambio_actual(pricing_db, "USD")
            return {
                str(r.item_id): _lines(r.producto_item_id, products, ppp, batches[store_of[str(r.item_id)]], rate)
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
    return {item_id: _lines(item_id, products, ppp, sell_in_out, rate) for item_id in ids}


def _lines(item_id: int, products: Mapping[int, tuple[Any, Any, Any]], ppp, sell_in_out, rate) -> dict[str, Any]:
    costo, moneda, iva = products[item_id]
    moneda = getattr(moneda, "value", moneda) or "ARS"
    ppp_payload = PppMarkups(ppp.get(item_id), moneda_costo=moneda, tipo_cambio=rate).payload()
    product = _CostedProduct(item_id, _as_float(costo), moneda, _as_float(iva))
    sio_payload = sell_in_out.markups(product, tipo_cambio=rate).payload()
    return {
        "ppp": None if ppp_payload is None else ppp_payload.model_dump(),
        "sell_in_out": None if sio_payload is None else sio_payload.model_dump(),
    }


def _as_float(value: Any) -> Optional[float]:
    """A Numeric column's value (a Decimal) as the float the sell in arithmetic mixes it with."""
    return None if value is None else float(value)
