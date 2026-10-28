"""Productos' "Sin MLA" in the Producto view of Publicaciones (`con_mla=false`, S12e): the ERP products no publication
is linked to, which every other view of this screen cannot show because it starts from the publications.

"Has an MLA" is this screen's own source of truth: a `linked` row of `ml_item_product_links` at ANY variation (a
publication with variations links each variation, never the item). Productos reads the ERP mirror instead
(`tb_mercadolibre_items_publicados`), so its count can differ. As in Productos, the products in its two banlists are
left out (`items_sin_mla_banlist`, and `producto_banlist` by item id or EAN, which is the product code).

Only the filters that read the product apply; a filter about publications has nothing to ask of a product that has
none and is refused (422), never silently ignored. The publication views list nothing under it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.services.ml_daily_metrics.sales import NO_PRODUCT
from app.services.ml_publications.view import listing, products
from app.services.ml_publications.view.filters import FilterError, MarkupFilter, parse_filter
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres


@pytest.fixture()
def store(mlpub_pg):  # noqa: F811
    ProductoERP.__table__.create(bind=mlpub_pg)
    with mlpub_pg.begin() as conn:  # the banlists come with `productos_erp` (`conftest._create_publication_map`)
        seed.add_product(conn, 70, "A70", "Router AX", marca="TP-Link", stock=9)  # linked at item level
        seed.add_product(conn, 71, "B71", "Switch 8p", marca="Mercusys", stock=0)  # linked on a variation only
        seed.add_product(conn, 72, "C72", "Antena", marca="Ubiquiti", stock=4)  # no MLA
        seed.add_product(conn, 73, "D73", "Cable HDMI", marca="Kabel", stock=0)  # no MLA
        seed.add_product(conn, 74, "E74", "Banned by id", marca="Kabel")
        seed.add_product(conn, 75, "7790001", "Banned by EAN", marca="Kabel")
        seed.add_product(conn, 76, "G76", "Banned from Sin MLA", marca="Kabel")
        seed.add_product(conn, 77, "H77", "Inactive ban", marca="Kabel")  # its ban is off: listed
        seed.add_item(conn, "MLA1")
        seed.add_link(conn, "MLA1", 70)
        seed.add_item(conn, "MLA2")
        seed.add_variation(conn, "MLA2", 11)
        seed.add_link(conn, "MLA2", 71, variation_id=11)
        conn.execute(text("INSERT INTO producto_banlist (item_id, activo) VALUES (74, true), (77, false)"))
        conn.execute(text("INSERT INTO producto_banlist (ean, activo) VALUES ('7790001', true)"))
        conn.execute(text("INSERT INTO items_sin_mla_banlist (item_id) VALUES (76)"))
    return mlpub_pg


@pytest.fixture()
def db(store):
    session = sessionmaker(bind=store)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def sin_mla(**params):
    return parse_filter(con_mla=False, **params)


def keys(page) -> list[int]:
    return [row.product_item_id for row in page.rows]


class TestTheRows:
    def test_lists_the_products_no_publication_is_linked_to_by_name(self, db) -> None:
        page = products.list_products(db, sin_mla(), "titulo", False, 50, 0)
        assert keys(page) == [72, 73, 77]  # Antena, Cable HDMI, Inactive ban
        assert (page.total, page.mla_count) == (3, 0)
        row = page.rows[0]
        assert (row.title, row.sku, row.marca, row.stock, row.publications_count, row.units) == (
            "Antena",
            "C72",
            "Ubiquiti",
            4,
            0,
            0,
        )
        assert page.without_figures == {"72", "73", "77"}  # no publication: no Métricas figure

    def test_a_product_linked_only_on_a_variation_has_an_mla(self, db) -> None:
        assert 71 not in keys(products.list_products(db, sin_mla(), "titulo", False, 50, 0))

    def test_a_figure_sort_falls_back_to_the_name_since_there_is_no_figure(self, db) -> None:
        assert keys(products.list_products(db, sin_mla(), "facturado_30d", True, 50, 0)) == [72, 73, 77]

    def test_a_figure_first_falls_back_to_the_name_in_the_direction_asked_for_it(self, db) -> None:
        then = (("titulo", True),)
        assert products.applied_sort(sin_mla(), "facturado_30d", True, then) == ("titulo", True, ())
        assert products.applied_sort(sin_mla(), "facturado_30d", True, ()) == ("titulo", False, ())
        assert products.applied_sort(sin_mla(), "titulo", True, (("unidades_30d", True),)) == ("titulo", True, ())
        assert products.applied_sort(parse_filter(), "facturado_30d", True, then) == ("facturado_30d", True, then)
        assert keys(products.list_products(db, sin_mla(), "facturado_30d", True, 50, 0, then=then)) == [77, 73, 72]

    def test_pages_are_stable(self, db) -> None:
        first = products.list_products(db, sin_mla(), "titulo", False, 2, 0)
        second = products.list_products(db, sin_mla(), "titulo", False, 2, 2)
        assert (keys(first), keys(second), second.total) == ([72, 73], [77], 3)

    def test_without_the_filter_the_view_is_unchanged(self, db) -> None:
        assert parse_filter(con_mla=True) == parse_filter()


class TestFilters:
    def test_the_product_filters_apply(self, db) -> None:
        def listed(**params) -> list[int]:
            return keys(products.list_products(db, sin_mla(**params), "titulo", False, 50, 0))

        assert listed(marcas="KABEL") == [73, 77]
        assert listed(q="codigo:c72") == [72]
        assert listed(q="hdmi") == [73]  # the product name
        assert listed(q="*73") == [73]  # the code
        assert listed(stock="erp_con_stock") == [72]
        assert listed(stock="erp_sin_stock") == [73]  # 77 has no stock figure: unknown, never "sin stock"
        assert listed(producto="73") == [73]  # one product: the product panel asks its row this way
        assert listed(producto="70") == []  # it has an MLA

    @pytest.mark.parametrize(
        ("param", "params"),
        [
            ("estado", {"estado": "active"}),
            ("estado_excluir", {"estado_excluir": "paused"}),
            ("tiendas", {"tiendas": "57997"}),
            ("tipo", {"tipo": "full"}),
            ("vinculo", {"vinculo": "auto"}),
            ("stock", {"stock": "sin_stock"}),
            ("evento", {"evento": "price_changed"}),
            ("familia", {"familia": "123"}),
            ("sin_producto", {"sin_producto": True}),
            ("con_oferta", {"con_oferta": True}),
            ("promo_tipos", {"mla_scope": frozenset({"MLA1"})}),
            ("q", {"q": "MLA1"}),
        ],
    )
    def test_a_publication_filter_is_refused_naming_its_parameter(self, db, param, params) -> None:
        with pytest.raises(FilterError) as raised:
            products.list_products(db, sin_mla(**params), "titulo", False, 50, 0)
        assert raised.value.field == param

    def test_the_publication_views_list_nothing(self, db) -> None:
        page = listing.list_items(db, sin_mla(), listing.parse_sort(None, None), 50, 0, events=False)
        assert (page.items, page.total) == ([], 0)


class TestTheCount:
    def test_counts_the_products_without_mla_under_the_product_filters(self, db) -> None:
        assert products.sin_mla_count(db, parse_filter()) == 3
        assert products.sin_mla_count(db, parse_filter(marcas="KABEL")) == 2

    def test_a_publication_filter_leaves_it_unknown(self, db) -> None:
        assert products.sin_mla_count(db, parse_filter(estado="active")) is None


class TestBulkAndExport:
    def test_product_ids_are_the_products_without_mla(self, db) -> None:
        found = products.product_ids(db, sin_mla())
        assert (found.item_ids, found.sin_producto, found.fuera_de_catalogo) == ([72, 73, 77], 0, 0)

    @pytest.mark.parametrize(
        ("markup", "param"),
        [
            (MarkupFilter(negative=True), "markup_neg"),
            (MarkupFilter(minimum=5.0), "markup_min"),
            (MarkupFilter(maximum=9.0), "markup_max"),
        ],
    )
    def test_a_markup_filter_is_refused_naming_its_parameter(self, db, markup, param) -> None:
        with pytest.raises(FilterError) as raised:
            products.product_ids(db, sin_mla(), SimpleNamespace(filter=markup))
        assert raised.value.field == param

    def test_product_ids_over_the_cap_are_refused(self, db, monkeypatch) -> None:
        monkeypatch.setattr(products, "MAX_PRODUCT_IDS", 2)
        with pytest.raises(products.TooManyProducts) as raised:
            products.product_ids(db, sin_mla())
        assert raised.value.count == 3

    def test_the_export_reads_the_same_rows_in_the_same_order(self, db) -> None:
        ordered = products.ordered_product_keys(db, sin_mla(), "titulo", False, None)
        assert ordered == [72, 73, 77]
        page = products.products_for_keys(db, sin_mla(), [73, 72, NO_PRODUCT, 70])
        assert keys(page) == [73, 72]  # a key that has an MLA (or none) is not a Sin MLA row
