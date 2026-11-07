"""The two lines Productos draws under a product's cost, for the Costo cell of Publicaciones ML (publication, detail
and product rows): the PPP and the cost with sell in.

Its own module because the sell in resolver is a catalog read (`productos_sell_in_out`), opened in this package only
to the view extraction modules (`tests/services/ml_publications/test_resources.py`); the listing reaches it through
here, as `view/detail.py` does for one publication.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.costo_ppp_service import PppMarkups, resolver_ppp_batch
from app.services.pricing_calculator import obtener_tipo_cambio_actual
from app.services.productos_sell_in_out import ContextoMarkup, resolver_sell_in_out_batch

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
    pricing_db: Session,
    products: Mapping[int, tuple[Any, Any, Any]],
    *,
    contextos: Optional[Sequence[ContextoMarkup]] = None,
) -> Optional[dict[int, dict[str, Any]]]:
    """The two lines Productos draws under a product's cost, per product id of `products` (id -> cost, currency,
    VAT): `ppp` (`resolver_ppp_batch` + `PppMarkups`, null without a qualifying row) and `sell_in_out`
    (`resolver_sell_in_out_batch`, null when neither applies). No markup is recorded: the cost cell shows neither.
    Both resolvers read the pricing database, once for the whole page.

    `contextos`: optional store/channel selection for tactical companions (Publicaciones: the row's official store).
    `None` keeps the pre-scope global read (product rows without a publication store).

    None when one of those reads fails (a database error, logged): the lines are informative, so the page answers as it did before they
    existed, each row with its cost and without the line keys, instead of failing whole. The reads run in a
    savepoint, so a failed one leaves the session usable for the rest of the request."""
    if not products:
        return {}
    try:
        with pricing_db.begin_nested():
            return _cost_lines(pricing_db, products, contextos=contextos)
    except SQLAlchemyError:  # a failed read; a programming error still surfaces
        logger.exception("Publicaciones ML: no se pudieron armar las líneas de PPP / sell in del costo")
        return None


def cost_lines_by_store(
    pricing_db: Session, by_store: Mapping[Optional[int], Mapping[int, tuple[Any, Any, Any]]]
) -> Optional[dict[tuple[Optional[int], int], dict[str, Any]]]:
    """Like `cost_lines`, keyed by `(official_store_id, product_id)` so two publications of the same product on
    different stores each get the tactical companions that reach that store."""
    if not by_store:
        return {}
    try:
        with pricing_db.begin_nested():
            out: dict[tuple[Optional[int], int], dict[str, Any]] = {}
            for store_id, products in by_store.items():
                partial = _cost_lines(pricing_db, products, contextos=[("ml", store_id)])
                for product_id, payload in partial.items():
                    out[(store_id, product_id)] = payload
            return out
    except SQLAlchemyError:
        logger.exception("Publicaciones ML: no se pudieron armar las líneas de PPP / sell in del costo")
        return None


def _cost_lines(
    pricing_db: Session,
    products: Mapping[int, tuple[Any, Any, Any]],
    *,
    contextos: Optional[Sequence[ContextoMarkup]] = None,
) -> dict[int, dict[str, Any]]:
    ids = sorted(products)
    ppp = resolver_ppp_batch(pricing_db, ids)
    sell_in_out = resolver_sell_in_out_batch(pricing_db, ids, date.today(), contextos=contextos)
    rate = obtener_tipo_cambio_actual(pricing_db, "USD")
    out: dict[int, dict[str, Any]] = {}
    for item_id in ids:
        costo, moneda, iva = products[item_id]
        moneda = getattr(moneda, "value", moneda) or "ARS"
        ppp_payload = PppMarkups(ppp.get(item_id), moneda_costo=moneda, tipo_cambio=rate).payload()
        product = _CostedProduct(item_id, _as_float(costo), moneda, _as_float(iva))
        sio_payload = sell_in_out.markups(product, tipo_cambio=rate).payload()
        out[item_id] = {
            "ppp": None if ppp_payload is None else ppp_payload.model_dump(),
            "sell_in_out": None if sio_payload is None else sio_payload.model_dump(),
        }
    return out


def group_products_by_store(
    rows: Sequence[Any],
) -> dict[Optional[int], dict[int, tuple[Any, Any, Any]]]:
    """`official_store_id -> {producto_item_id: (costo, moneda, iva)}` for `cost_lines_by_store`."""
    by_store: dict[Optional[int], dict[int, tuple[Any, Any, Any]]] = defaultdict(dict)
    for row in rows:
        product_id = getattr(row, "producto_item_id", None)
        if not product_id:
            continue
        by_store[getattr(row, "official_store_id", None)][product_id] = (
            row.costo,
            row.moneda_costo,
            getattr(row, "costo_iva", getattr(row, "iva", None)),
        )
    return by_store


def _as_float(value: Any) -> Optional[float]:
    """A Numeric column's value (a Decimal) as the float the sell in arithmetic mixes it with."""
    return None if value is None else float(value)
