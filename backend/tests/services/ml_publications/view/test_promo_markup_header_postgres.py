"""S11: a promo at the header's price shows the header's markup.

Owner (2026-11-12): header "Precio $ 52.000,00 Markup 12,7%" vs the promo card "SELLER_CAMPAIGN ... $52.000 ...
Tu markup:4.7%": "se están contradiciendo los markups" -> "arreglalo". The promo markup priced (A) the list of an
arbitrary `publicaciones_ml` row instead of the list ML charges the item (`resolve_pricelist`), and (B) the
product's shipping instead of the publication's own cost first. Rule: at the same revenue, the promo markup equals
the header's `unit_markup` of that MLA; ML co-funding still adds to the revenue.

Same world as the header's own tests (`test_markup_service_postgres.py`): the stored publication, the hand-built
pricing context, the shipping read stubbed.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.envio_real_service import CostosEnvio
from app.services.ml_promotions_pricing import (
    enriquecer_markup_por_promo,
    markup_para_precio,
    markup_para_precio_con_sell_in_out,
)
from app.services.ml_publications.view import markup_service
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx

pytestmark = pytest.mark.postgres

MLA = "MLA1"
PRODUCT = 70
HEADER_PRICE = 52000.0
PRODUCT_SHIPPING = {PRODUCT: 1500.0}  # the product's MAX of its publications' real costs


@pytest.fixture()
def conn(env):  # noqa: F811
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(seed.PRICING_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def own_costs() -> dict[str, float]:
    return {}


@pytest.fixture(autouse=True)
def stubs(monkeypatch, own_costs):
    """The header's shipping read and pricing context, shared by the header and the promo."""

    def fake_shipping(session, product_ids, mla_ids, **kwargs):
        return CostosEnvio(
            por_producto={k: v for k, v in PRODUCT_SHIPPING.items() if k in product_ids},
            por_mla={m: own_costs[m] for m in mla_ids if m in own_costs},
        )

    monkeypatch.setattr(markup_service, "resolver_costos_envio_mlas", fake_shipping)
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda *a, **k: make_ctx())


def _terms(campaign: str) -> str:
    return json.dumps({"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": campaign}]})


# (A) the list ML charges the item: 9x by tag, 12x by sale term only, the classic list.
LISTS = {
    "nine_by_tag": dict(listing_type_id="gold_pro", tags=["9x_campaign"]),
    "twelve_by_sale_term": dict(listing_type_id="gold_pro", raw=_terms("12x_campaign")),
    "classic": dict(listing_type_id="gold_special"),
}


def _seed(conn, item: dict) -> None:
    seed.add_product(conn, PRODUCT, "C70", "Producto 70", subcategoria_id=3845)
    seed.add_cost(conn, PRODUCT, 40000.0)
    seed.add_item(conn, MLA, price=HEADER_PRICE + 5000, **item)
    seed.add_sale_price(conn, MLA, HEADER_PRICE)
    seed.add_link(conn, MLA, PRODUCT)


def _header(db) -> tuple[float, float]:
    found = markup_service.compute_detail(db, db, MLA)
    assert found is not None and found.breakdown is not None
    return found.breakdown.price, found.breakdown.markup


def _seller_campaign(price: float) -> dict:
    return {"mla": MLA, "promotion_id": "C-1", "promotion_type": "SELLER_CAMPAIGN", "status": "started", "price": price}


@pytest.mark.parametrize("own_shipping", [None, 4200.0], ids=["product_shipping", "own_shipping_B"])
@pytest.mark.parametrize("item", list(LISTS.values()), ids=list(LISTS))
def test_promo_at_the_header_price_shows_the_header_markup(conn, db, own_costs, item, own_shipping) -> None:
    _seed(conn, item)
    if own_shipping is not None:
        own_costs[MLA] = own_shipping
    price, header_markup = _header(db)
    assert price == HEADER_PRICE

    promo = enriquecer_markup_por_promo(db, MLA, [_seller_campaign(price)])[0]

    assert promo["nuestro_markup"] == pytest.approx(header_markup)
    assert markup_para_precio(db, MLA, price) == pytest.approx(header_markup)
    assert markup_para_precio_con_sell_in_out(db, MLA, price).nuestro_markup == pytest.approx(header_markup)


def test_own_shipping_moves_the_promo_markup_like_the_header(conn, db, own_costs) -> None:
    _seed(conn, LISTS["nine_by_tag"])
    without_own = enriquecer_markup_por_promo(db, MLA, [_seller_campaign(HEADER_PRICE)])[0]["nuestro_markup"]
    own_costs[MLA] = 4200.0  # above the product's 1500: the publication's own cost wins

    with_own = enriquecer_markup_por_promo(db, MLA, [_seller_campaign(HEADER_PRICE)])[0]["nuestro_markup"]

    assert with_own < without_own
    assert with_own == pytest.approx(_header(db)[1])


def test_variations_on_two_products_price_the_promo_on_the_headers_worst_unit(conn, db) -> None:
    """The header's breakdown ("Unidad calculada" / Rentabilidad) explains the worst variation: the promo prices
    that same unit, never the item-level product or the cheaper sibling."""
    seed.add_product(conn, PRODUCT, "C70", "Producto 70", subcategoria_id=3845)
    seed.add_cost(conn, PRODUCT, 40000.0)
    seed.add_product(conn, 72, "C72", "Producto 72", subcategoria_id=3845)
    seed.add_cost(conn, 72, 46000.0)  # the dearer product: the worst variation
    seed.add_item(conn, MLA, price=HEADER_PRICE + 5000, **LISTS["nine_by_tag"])
    seed.add_sale_price(conn, MLA, HEADER_PRICE)
    seed.add_link(conn, MLA, PRODUCT)  # item level
    seed.add_variation(conn, MLA, 11)
    seed.add_variation(conn, MLA, 12)
    seed.add_link(conn, MLA, PRODUCT, variation_id=11)
    seed.add_link(conn, MLA, 72, variation_id=12)

    found = markup_service.compute_detail(db, db, MLA)
    promo = enriquecer_markup_por_promo(db, MLA, [_seller_campaign(HEADER_PRICE)])[0]

    assert found.item.markup.is_range and found.variation_id == 12
    assert found.breakdown.markup == pytest.approx(found.item.markup.worst)
    assert promo["nuestro_markup"] == pytest.approx(found.item.markup.worst)
    assert promo["nuestro_markup"] < found.item.markup.value_max


@pytest.mark.parametrize(
    "item, link, cost",
    [
        (dict(listing_type_id="free"), True, 40000.0),  # no list of ours: header "sin_lista"
        (LISTS["nine_by_tag"], True, None),  # product without cost: header "sin_costo"
        (LISTS["nine_by_tag"], False, 40000.0),  # no linked product: header "sin_vinculo"
    ],
    ids=["sin_lista", "sin_costo", "sin_vinculo"],
)
def test_a_publication_without_header_markup_gets_no_promo_markup(conn, db, item, link, cost) -> None:
    seed.add_product(conn, PRODUCT, "C70", "Producto 70", subcategoria_id=3845)
    if cost is not None:
        seed.add_cost(conn, PRODUCT, cost)
    seed.add_item(conn, MLA, price=HEADER_PRICE + 5000, **item)
    seed.add_sale_price(conn, MLA, HEADER_PRICE)
    if link:
        seed.add_link(conn, MLA, PRODUCT)
    assert markup_service.compute_detail(db, db, MLA).breakdown is None  # the header shows no markup

    promo = enriquecer_markup_por_promo(db, MLA, [_seller_campaign(HEADER_PRICE)], sell_in_out=True)[0]

    assert promo["nuestro_markup"] is None and promo["markup_sell_in_out"] is None
    assert markup_para_precio_con_sell_in_out(db, MLA, HEADER_PRICE) == (None, None)
    assert db.execute(text("SELECT 1")).scalar() == 1  # the session is still usable


def test_an_mla_not_in_the_store_gets_no_promo_markup(db) -> None:
    assert enriquecer_markup_por_promo(db, "MLA404", [_seller_campaign(HEADER_PRICE)])[0]["nuestro_markup"] is None
    assert markup_para_precio(db, "MLA404", HEADER_PRICE) is None


def test_co_funding_still_adds_to_the_revenue(conn, db) -> None:
    _seed(conn, LISTS["nine_by_tag"])
    smart = {
        "mla": MLA,
        "promotion_id": "S-1",
        "promotion_type": "SMART",
        "status": "started",
        "price": 48000.0,
        "original_price": HEADER_PRICE,
        "payload": {"meli_percentage": 5.0},
    }

    got = enriquecer_markup_por_promo(db, MLA, [smart])[0]["nuestro_markup"]

    assert got == pytest.approx(markup_para_precio(db, MLA, 48000.0 + 0.05 * HEADER_PRICE))
    assert got > markup_para_precio(db, MLA, 48000.0)
