"""Characterization of the markup computation: its exact figures, pinned before it was optimized.

The expected values below were captured from the unoptimized implementation, then every optimization had to keep
them byte-identical (`==` on floats, no tolerance). The set covers a publication with and without variations, a
variation without its own link, a gone variation, no link, no cost, a negative markup, a promo (sale) price, the
item price, the Productos list-price fallback (with and without a pricing row), a USD cost, every list the
resolver knows and the ones it refuses. Both paths (explicit ids and a filter), the tree and the detail are pinned.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_publications.view.markup import UnitBreakdown
from app.services.ml_publications.view import groups, listing, markup_service
from app.services.ml_publications.view.filters import MarkupFilter, parse_filter
from app.services.ml_publications.view.markup_service import MarkupQuery
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL
from tests.services.ml_publications.view.test_unit_markup import make_ctx

pytestmark = pytest.mark.postgres

ENVIO = {70: 1500.0}


@pytest.fixture()
def conn(env):  # noqa: F811
    SubcategoriaGrupo.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
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


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx())
    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", lambda session, ids, **kw: dict(ENVIO))


def terms(campaign: str) -> str:
    return json.dumps({"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": campaign}]})


def seed_catalog(conn) -> None:
    products = (
        (70, "Alfa", 50000.0, "ARS", 21.0, 0.0),
        (71, "Alfa", None, "ARS", 21.0, 0.0),  # never costed
        (72, "Beta", 60.0, "USD", 21.0, 0.0),  # a USD cost
        (73, "Beta", 400000.0, "ARS", 21.0, 0.0),  # dearer than any price: a negative markup
        (74, "Gamma", 30000.0, "ARS", 10.5, 800.0),  # has Productos list prices
        (75, "Gamma", 20000.0, "ARS", 21.0, 0.0),  # has none
    )
    for item_id, brand, costo, currency, iva, envio in products:
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", marca=brand, subcategoria_id=3845)
        seed.add_cost(conn, item_id, costo, moneda_costo=currency, iva=iva, envio=envio)
    seed.add_pricing(conn, 74, precio_lista_ml=100000.0, precio_6_cuotas=88000.0, precio_9_cuotas=95000.0)
    items = {
        "MLA1": dict(listing_type_id="gold_pro", tags=["9x_campaign"], price=90000, sale=100000, link=70),  # promo
        "MLA2": dict(listing_type_id="gold_pro", price=90000, link=70),  # item price, 6x list
        "MLA3": dict(listing_type_id="gold_pro", link=74),  # list-price fallback, 6x list
        "MLA4": dict(listing_type_id="gold_pro", tags=["9x_campaign"], price=0, link=74),  # fallback, 9x list
        "MLA5": dict(listing_type_id="gold_pro", link=75),  # no price and no pricing row
        "MLA6": dict(listing_type_id="gold_special", price=70000, link=72),  # classic list, USD cost
        "MLA7": dict(listing_type_id="gold_pro", price=120000, raw=terms("12x_campaign"), link=73),  # negative
        "MLA8": dict(listing_type_id="gold_pro", price=90000),  # no link
        "MLA9": dict(listing_type_id="gold_pro", price=90000, link=71),  # no cost
        "MLA10": dict(listing_type_id="free", price=90000, link=70),  # no list of ours
        "MLA11": dict(listing_type_id="gold_special", tags=["pcj-co-funded"], price=90000, link=70),
        "MLA12": dict(listing_type_id="gold_pro", tags=["3x_campaign"], price=90000, link=72),  # variations
        "MLA13": dict(listing_type_id="gold_pro", price=90000),  # variations, no item-level link
        "MLA14": dict(listing_type_id="gold_pro", price=90000, link=70),  # a live and a gone variation
        "MLA15": dict(listing_type_id="gold_pro", price=90000, sale=99, sale_status=404, link=70),  # sale failed
        "MLA16": dict(listing_type_id="gold_pro", price=90000, raw=terms("7x_campaign"), link=70),  # unknown campaign
        "MLA17": dict(listing_type_id="gold_pro", price=90000, sale=95000, link=74),  # USD-free, iva 10.5, envio
    }
    for item_id, spec in items.items():
        columns = {k: v for k, v in spec.items() if k in ("listing_type_id", "tags", "price", "raw")}
        seed.add_item(conn, item_id, **columns)
        if "sale" in spec:
            seed.add_sale_price(conn, item_id, spec["sale"], http_status=spec.get("sale_status", 200))
        if spec.get("link"):
            seed.add_link(conn, item_id, spec["link"])
    for item_id, variation_id, product in (
        ("MLA12", 11, 70),
        ("MLA12", 12, 73),
        ("MLA12", 13, None),  # no link of its own: the item-level unit prices it
        ("MLA13", 21, 70),
        ("MLA13", 22, None),  # nothing to fall back to: sin_vinculo
        ("MLA14", 31, 70),
    ):
        seed.add_variation(conn, item_id, variation_id)
        if product:
            seed.add_link(conn, item_id, product, variation_id=variation_id)
    seed.add_variation(conn, "MLA14", 32, gone_at=datetime.now(timezone.utc))
    seed.add_link(conn, "MLA14", 73, variation_id=32)


def snapshot(result) -> dict:
    """Every figure of every publication, as plain tuples."""
    return {
        item_id: (
            item.variation_ids,
            item.markup.value_min,
            item.markup.value_max,
            item.markup.worst,
            item.markup.any_negative,
            item.markup.partial,
            item.markup.reason,
            tuple(
                (u.value, u.reason, u.limpio, u.costo_ars, u.price, u.source, u.pricelist_id)
                for u in item.markup.variations
            ),
        )
        for item_id, item in sorted(result.items.items())
    }


def tree(db):
    page = groups.list_groups(db, parse_filter(), [], markup=MarkupQuery(db))
    return {n.key: (n.count, n.negative_count, n.markup_min, n.markup_max) for n in page.nodes}


# Captured from the implementation before the optimization (see the module docstring).
EXPECTED = {
    "MLA1": (
        (),
        -2.975206611570236,
        -2.975206611570236,
        -2.975206611570236,
        True,
        0,
        "ok",
        ((-2.975206611570236, "ok", 48512.39669421488, 50000.0, 100000.0, "sale_price", 13),),
    ),
    "MLA10": ((), None, None, None, False, 0, "sin_lista", ((None, "sin_lista", None, None, None, None, None),)),
    "MLA11": ((), None, None, None, False, 0, "cofinanciada", ((None, "cofinanciada", None, None, None, None, None),)),
    "MLA12": (
        (11, 12, 13),
        -87.56404958677686,
        0.31404958677685446,
        -87.56404958677686,
        True,
        0,
        "ok",
        (
            (0.31404958677685446, "ok", 50157.024793388424, 50000.0, 90000.0, "item_price", 17),
            (-87.56404958677686, "ok", 49743.80165289255, 400000.0, 90000.0, "item_price", 17),
            (-17.093663911845745, "ok", 49743.80165289255, 60000.0, 90000.0, "item_price", 17),
        ),
    ),
    "MLA13": (
        (21, 22),
        -6.380165289256201,
        -6.380165289256201,
        -6.380165289256201,
        True,
        1,
        "ok",
        (
            (-6.380165289256201, "ok", 46809.9173553719, 50000.0, 90000.0, "item_price", 14),
            (None, "sin_vinculo", None, None, None, None, None),
        ),
    ),
    "MLA14": (
        (31,),
        -6.380165289256201,
        -6.380165289256201,
        -6.380165289256201,
        True,
        0,
        "ok",
        ((-6.380165289256201, "ok", 46809.9173553719, 50000.0, 90000.0, "item_price", 14),),
    ),
    "MLA15": (
        (),
        -6.380165289256201,
        -6.380165289256201,
        -6.380165289256201,
        True,
        0,
        "ok",
        ((-6.380165289256201, "ok", 46809.9173553719, 50000.0, 90000.0, "item_price", 14),),
    ),
    "MLA16": ((), None, None, None, False, 0, "sin_lista", ((None, "sin_lista", None, None, None, None, None),)),
    "MLA17": (
        (),
        90.11125238397966,
        90.11125238397966,
        90.11125238397966,
        False,
        0,
        "ok",
        ((90.11125238397966, "ok", 57033.3757151939, 30000.0, 95000.0, "sale_price", 14),),
    ),
    "MLA2": (
        (),
        -6.380165289256201,
        -6.380165289256201,
        -6.380165289256201,
        True,
        0,
        "ok",
        ((-6.380165289256201, "ok", 46809.9173553719, 50000.0, 90000.0, "item_price", 14),),
    ),
    "MLA3": (
        (),
        75.94066539521087,
        75.94066539521087,
        75.94066539521087,
        False,
        0,
        "ok",
        ((75.94066539521087, "ok", 52782.19961856326, 30000.0, 88000.0, "productos_fallback", 14),),
    ),
    "MLA4": (
        (),
        78.59610086882813,
        78.59610086882813,
        78.59610086882813,
        False,
        0,
        "ok",
        ((78.59610086882813, "ok", 53578.83026064844, 30000.0, 95000.0, "productos_fallback", 13),),
    ),
    "MLA5": ((), None, None, None, False, 0, "sin_precio", ((None, "sin_precio", None, None, None, None, 14),)),
    "MLA6": (
        (),
        -27.548209366391173,
        -27.548209366391173,
        -27.548209366391173,
        True,
        0,
        "ok",
        ((-27.548209366391173, "ok", 43471.07438016529, 60000.0, 70000.0, "item_price", 4),),
    ),
    "MLA7": (
        (),
        -86.42975206611571,
        -86.42975206611571,
        -86.42975206611571,
        True,
        0,
        "ok",
        ((-86.42975206611571, "ok", 54280.99173553718, 400000.0, 120000.0, "item_price", 23),),
    ),
    "MLA8": ((), None, None, None, False, 0, "sin_vinculo", ((None, "sin_vinculo", None, None, None, None, None),)),
    "MLA9": ((), None, None, None, False, 0, "sin_costo", ((None, "sin_costo", None, None, None, None, None),)),
}
EXPECTED_STATS = (11, {"sin_precio": 1, "sin_vinculo": 1, "sin_costo": 1, "sin_lista": 2, "cofinanciada": 1})
EXPECTED_TREE = {
    "ALFA": (8, 4, -6.380165289256201, -2.975206611570236),
    "BETA": (3, 3, -87.56404958677686, 0.31404958677685446),
    "GAMMA": (4, 0, 75.94066539521087, 90.11125238397966),
    "__none__": (2, 1, -6.380165289256201, -6.380165289256201),
}
EXPECTED_DETAIL = (
    12,
    UnitBreakdown(
        price=90000.0,
        price_source="item_price",
        pricelist_id=17,
        installments=3,
        comision_pct=24.4,
        comision_total=22983.471074380166,
        costo_envio=2000.0,
        envio_source="grupo_promedio",
        limpio=49743.80165289255,
        costo_ars=400000.0,
        markup=-87.56404958677686,
    ),
)


class TestCharacterization:
    def test_the_figures_of_every_publication_by_a_filter(self, conn, db) -> None:
        seed_catalog(conn)
        got = snapshot(markup_service.compute_markups(db, db, f=parse_filter()))
        assert got == EXPECTED

    def test_the_figures_of_every_publication_by_ids(self, conn, db) -> None:
        seed_catalog(conn)
        got = snapshot(markup_service.compute_markups(db, db, item_ids=[f"MLA{n}" for n in range(17, 0, -1)]))
        assert got == EXPECTED

    def test_the_stats(self, conn, db) -> None:
        seed_catalog(conn)
        stats = markup_service.compute_markups(db, db, f=parse_filter()).stats
        assert stats.computed == EXPECTED_STATS[0] and dict(stats.null_by_reason) == EXPECTED_STATS[1]

    def test_the_root_of_the_tree(self, conn, db) -> None:
        seed_catalog(conn)
        assert tree(db) == EXPECTED_TREE

    def test_the_detail_of_a_variation_publication(self, conn, db) -> None:
        seed_catalog(conn)
        detail = markup_service.compute_detail(db, db, "MLA12")
        assert (detail.variation_id, detail.breakdown) == EXPECTED_DETAIL


def ids(order: str) -> list[str]:
    return [f"MLA{token}" for token in order.split()]


def page(db, sort=None, descending=None, markup_filter=MarkupFilter(), limit=50, offset=0):
    """The list as the router builds it: `(total, [(item_id, markup block)])`, captured before the optimizations."""
    result = listing.list_items(
        db,
        parse_filter(),
        listing.parse_sort(sort, descending),
        limit,
        offset,
        events=False,
        markup=MarkupQuery(db, markup_filter),
    )
    return result.total, [(row["item_id"], row["markup"]) for row in result.items]


# Captured from the implementation before the optimizations (see the module docstring).
BY_MARKUP = "12 7 6 13 14 15 2 1 3 4 17 10 11 16 5 8 9"  # worst first; the unpriced last, by item id
BY_MARKUP_DESC = "17 4 3 1 13 14 15 2 6 7 12 10 11 16 5 8 9"
DEFAULT_ORDER = "1 10 11 12 13 14 15 16 17 2 3 4 5 6 7 8 9"
NEGATIVE = "1 12 13 14 15 2 6 7"  # any variation negative, in the default (item id) order
IN_RANGE = "13 14 15 2 1 3 4"  # worst markup within [-10, 80], worst first
BLOCKS = {
    "MLA12": {"min": -87.56, "max": 0.31, "worst": -87.56, "any_negative": True, "reason": "ok", "partial": 0},
    "MLA13": {"min": -6.38, "max": -6.38, "worst": -6.38, "any_negative": True, "reason": "ok", "partial": 1},
    "MLA3": {"min": 75.94, "max": 75.94, "worst": 75.94, "any_negative": False, "reason": "ok", "partial": 0},
    "MLA10": {"min": None, "max": None, "worst": None, "any_negative": False, "reason": "sin_lista", "partial": 0},
    "MLA11": {"min": None, "max": None, "worst": None, "any_negative": False, "reason": "cofinanciada", "partial": 0},
}


class TestListCharacterization:
    """The list over the same catalog: the order, the page and the filters of the markup, and each row's block."""

    def test_sorted_by_markup_ascending_and_descending(self, conn, db) -> None:
        seed_catalog(conn)
        total, rows = page(db, "markup")
        assert (total, [item_id for item_id, _ in rows]) == (17, ids(BY_MARKUP))
        total, rows = page(db, "markup", "desc")
        assert (total, [item_id for item_id, _ in rows]) == (17, ids(BY_MARKUP_DESC))

    def test_a_page_of_the_markup_order(self, conn, db) -> None:
        seed_catalog(conn)
        total, rows = page(db, "markup", limit=5, offset=5)
        assert (total, [item_id for item_id, _ in rows]) == (17, ids(BY_MARKUP)[5:10])

    def test_the_markup_filters(self, conn, db) -> None:
        seed_catalog(conn)
        total, rows = page(db, markup_filter=MarkupFilter(negative=True))
        assert (total, [item_id for item_id, _ in rows]) == (8, ids(NEGATIVE))
        total, rows = page(db, "markup", markup_filter=MarkupFilter(minimum=-10, maximum=80))
        assert (total, [item_id for item_id, _ in rows]) == (7, ids(IN_RANGE))

    def test_the_default_order_carries_the_markup_of_its_page_only(self, conn, db) -> None:
        seed_catalog(conn)
        total, rows = page(db, limit=4, offset=2)
        assert (total, [item_id for item_id, _ in rows]) == (17, ids(DEFAULT_ORDER)[2:6])

    def test_the_markup_block_of_a_row(self, conn, db) -> None:
        seed_catalog(conn)
        _, rows = page(db, "markup")
        assert {item_id: block for item_id, block in rows if item_id in BLOCKS} == BLOCKS
