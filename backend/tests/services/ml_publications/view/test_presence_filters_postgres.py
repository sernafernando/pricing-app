"""S5: Productos' "Filtros de Presencia" on the Publicaciones ML list (`/view/items`, and so `/view/products`).

The same params and meaning as `GET /productos`: rebate, web transferencia and out of cards are flags of the
LINKED product's `productos_pricing` row (no row reads "sin"); Tienda Nube is the product's active variants; mejor
oferta is a current `ofertas_ml` row of the publication itself (the Producto view asks it of the product, as
Productos does: `test_ml_publications_view_presence.py`). A publication without a linked product matches neither side of a product flag.
Row shapes follow production rows (product 3163's flags, product 1123 / 983's Tienda Nube variants, the latest
`ofertas_ml` row).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import FilterError, parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import conn, db, ids  # noqa: F401

pytestmark = pytest.mark.postgres

TODAY = date.today()


def run(db, **params):
    return listing.list_items(db, parse_filter(**params), listing.parse_sort(None, None), 50, 0, events=True)


def listed(db, **params) -> list[str]:
    page = run(db, **params)
    assert page.total == len(page.items)
    return sorted(ids(page))


@pytest.fixture(autouse=True)
def rows(conn) -> None:  # noqa: F811
    seed.create_presence_tables(conn, with_pricing=True)
    seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", stock=5)
    seed.add_product(conn, 71, "B1", "Camara", marca="Hikvision", stock=0)
    seed.add_product(conn, 72, "C1", "Switch", marca="TP-Link", stock=3)  # no pricing row, not in Tienda Nube
    for mla in ("MLA1", "MLA2", "MLA3", "MLA4", "MLA5"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 70)
    seed.add_link(conn, "MLA5", 70)  # a second publication of the same product
    seed.add_link(conn, "MLA2", 71)
    seed.add_link(conn, "MLA3", 72)  # MLA4: no product
    seed.add_pricing(conn, 70, participa_rebate=True, participa_web_transferencia=True, out_of_cards=True)
    seed.add_pricing(conn, 71, participa_rebate=False, participa_web_transferencia=True, out_of_cards=False)
    # two active variants of 70, both on sale: the publication is still listed once
    seed.add_tn_variant(conn, 70, 1182988920, price=167021, promotional_price=93380, activo=True)
    seed.add_tn_variant(conn, 70, 1182988921, price=167021, promotional_price=93380, activo=True)
    seed.add_tn_variant(conn, 71, 1182984711, price=22231, promotional_price=None, activo=True)
    seed.add_tn_variant(conn, 72, 1182984712, price=1000, promotional_price=500, activo=False)  # gone from TN
    seed.add_oferta(
        conn, "MLA1", TODAY - timedelta(days=5), TODAY + timedelta(days=5), precio_final=83200, pvp_seller=86486
    )
    seed.add_oferta(conn, "MLA2", date(2026, 5, 8), date(2026, 5, 31), precio_final=83200, pvp_seller=86486)  # over
    # current (wide window, see MLA1) but no seller price: not one
    seed.add_oferta(
        conn, "MLA3", TODAY - timedelta(days=5), TODAY + timedelta(days=5), precio_final=83200, pvp_seller=None
    )


class TestProductFlags:
    def test_rebate(self, db) -> None:
        assert listed(db, con_rebate=True) == ["MLA1", "MLA5"]
        assert listed(db, con_rebate=False) == ["MLA2", "MLA3"]  # 72 has no pricing row: "sin"

    def test_web_transferencia(self, db) -> None:
        assert listed(db, con_web_transf=True) == ["MLA1", "MLA2", "MLA5"]
        assert listed(db, con_web_transf=False) == ["MLA3"]

    def test_out_of_cards(self, db) -> None:
        assert listed(db, out_of_cards=True) == ["MLA1", "MLA5"]
        assert listed(db, out_of_cards=False) == ["MLA2", "MLA3"]

    def test_a_publication_without_a_product_matches_neither_side(self, db) -> None:
        for param in ("con_rebate", "con_web_transf", "out_of_cards"):
            assert "MLA4" not in listed(db, **{param: True}) + listed(db, **{param: False})


class TestMejorOferta:
    def test_a_current_offer_with_a_seller_price_of_the_publication(self, db) -> None:
        assert listed(db, con_oferta=True) == ["MLA1"]
        assert listed(db, con_oferta=False) == ["MLA2", "MLA3", "MLA4", "MLA5"]


class TestTiendaNube:
    def test_con_descuento_lists_each_publication_once(self, db) -> None:
        assert listed(db, tn_con_descuento=True) == ["MLA1", "MLA5"]

    def test_sin_descuento(self, db) -> None:
        assert listed(db, tn_sin_descuento=True) == ["MLA2"]

    def test_no_publicado_is_in_stock_and_not_active_in_tienda_nube(self, db) -> None:
        assert listed(db, tn_no_publicado=True) == ["MLA3"]  # 71 has no stock; MLA4 has no product


class TestWithTheOtherFilters:
    def test_toggles_and_with_each_other_and_the_product_filters(self, db) -> None:
        assert listed(db, con_rebate=False, marcas="tp-link") == ["MLA3"]
        assert listed(db, con_web_transf=True, out_of_cards=False) == ["MLA2"]
        assert listed(db, con_rebate=True, con_oferta=True) == ["MLA1"]


class TestProductosMissingFilters:
    """P6: Productos' stock, precio and nuevos filters, with `GET /productos`' meaning, asked of the linked product."""

    def test_con_stock_erp_is_stock_above_zero_and_needs_a_product(self, db) -> None:
        assert listed(db, stock="erp_con_stock") == ["MLA1", "MLA3", "MLA5"]  # 71 has 0; MLA4 has no product
        assert listing.facets(db, parse_filter())["stock"]["erp_con_stock"] == 3  # the chip's count is what it lists

    def test_con_precio_is_a_list_price_in_productos_pricing(self, db, conn) -> None:
        conn.execute(text("UPDATE productos_pricing SET precio_lista_ml = 167021 WHERE item_id = 70"))
        assert listed(db, con_precio=True) == ["MLA1", "MLA5"]
        assert listed(db, con_precio=False) == ["MLA2", "MLA3"]  # 72 has no pricing row: "sin"; MLA4 neither side

    def test_nuevos_are_products_synced_in_the_last_7_days(self, db, conn) -> None:
        conn.execute(text("UPDATE productos_erp SET fecha_sync = now() - interval '8 days' WHERE item_id <> 71"))
        assert listed(db, nuevos_ultimos_7_dias=True) == ["MLA2"]
        assert len(listed(db, nuevos_ultimos_7_dias=False)) == 5  # false is no filter, as in Productos


class TestProductosMarkupFilters:
    """P6b: Productos' Markup Clásica / Rebate / Oferta / Web Transf. filters, its stored markups of the linked
    product: positive is > 0, negative < 0; a zero, a missing value or no pricing row matches neither side."""

    @pytest.fixture(autouse=True)
    def markups(self, conn) -> None:
        conn.execute(text(seed.MARKUP_DDL))
        conn.execute(
            text(
                "UPDATE productos_pricing SET markup_calculado = 12.5, markup_rebate = -3, markup_oferta = 0, "
                "markup_web_real = NULL WHERE item_id = 70"
            )
        )
        conn.execute(
            text(
                "UPDATE productos_pricing SET markup_calculado = -8, markup_rebate = 4, markup_oferta = 2, "
                "markup_web_real = -1 WHERE item_id = 71"
            )
        )

    @pytest.mark.parametrize(
        ("param", "positive", "negative"),
        [
            ("markup_clasica_positivo", ["MLA1", "MLA5"], ["MLA2"]),
            ("markup_rebate_positivo", ["MLA2"], ["MLA1", "MLA5"]),
            ("markup_oferta_positivo", ["MLA2"], []),  # 70's zero is neither
            ("markup_web_transf_positivo", [], ["MLA2"]),  # 70's NULL is neither
        ],
    )
    def test_each_markup_by_its_sign(self, db, param, positive, negative) -> None:
        assert listed(db, **{param: True}) == positive
        assert listed(db, **{param: False}) == negative  # MLA3 (no pricing row) and MLA4 (no product): neither


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


class TestProductosAuditFilter:
    """P6c: Productos' audit filter (who changed the product, what kind of change, when), asked of the linked
    product's `auditoria` rows. Dates are Buenos Aires wall time, as Productos reads them; the column is UTC."""

    @pytest.fixture(autouse=True)
    def users(self, conn) -> tuple[int, int]:
        seed.create_audit_tables(conn)
        ana, beto = seed.add_user(conn, "Ana", "ana"), seed.add_user(conn, "Beto", "beto")
        # the ORM (`SQLEnum(TipoAccion)`, not native) stores the member NAME; the API speaks the value
        seed.add_auditoria(conn, "MODIFICAR_PRECIO_CLASICA", {}, utc(2026, 10, 20, 15, 0), ana, item_id=70)  # 12:00 BA
        seed.add_auditoria(conn, "ACTIVAR_REBATE", {}, utc(2026, 10, 22, 2, 30), beto, item_id=71)  # 21 Oct 23:30 BA
        seed.add_auditoria(conn, "MODIFICAR_PRECIO_CLASICA", {}, utc(2026, 10, 21, 12, 0), ana)  # a bulk row
        return ana, beto

    def test_by_user_and_by_kind(self, db, users) -> None:
        ana, beto = users
        assert listed(db, audit_usuarios=str(ana)) == ["MLA1", "MLA5"]
        assert listed(db, audit_tipos_accion="activar_rebate") == ["MLA2"]
        assert listed(db, audit_usuarios=f"{ana},{beto}", audit_tipos_accion="activar_rebate") == ["MLA2"]

    def test_by_date_in_buenos_aires_time(self, db) -> None:
        assert listed(db, audit_fecha_desde="2026-10-21") == ["MLA2"]  # 23:30 on the 21st in BA
        assert listed(db, audit_fecha_hasta="2026-10-21") == ["MLA1", "MLA2", "MLA5"]  # the whole day
        assert listed(db, audit_fecha_desde="2026-10-20 12:01") == ["MLA2"]
        assert listed(db, audit_fecha_hasta="2026-10-20 12:00") == ["MLA1", "MLA5"]

    @pytest.mark.parametrize(
        ("param", "value"),
        [("audit_usuarios", "ana"), ("audit_tipos_accion", "borrar_todo"), ("audit_fecha_desde", "ayer")],
    )
    def test_a_value_outside_the_vocabulary_is_an_error(self, param, value) -> None:
        with pytest.raises(FilterError) as raised:
            parse_filter(**{param: value})
        assert raised.value.field == param


class TestMlaScope:
    """P6d: the promo and PxQ filters resolve, in the router, to the set of MLAs that match (from the mlwebhook
    database); the filter narrows the list to it. An empty set lists nothing, never everything."""

    def test_the_list_is_narrowed_to_the_resolved_mlas(self, db) -> None:
        assert listed(db, mla_scope=frozenset({"MLA2", "MLA4", "MLA9"})) == ["MLA2", "MLA4"]

    def test_an_empty_scope_lists_nothing(self, db) -> None:
        assert listed(db, mla_scope=frozenset()) == []


class TestEstadoMlaPausada:
    """Productos' "Estado MLA: Pausadas" (`estado_mla=pausada`, `GET /productos`): the linked product has
    publications and none of them is active. As in Productos, a publication with no status counts as active, and a
    closed or deleted one as not active."""

    @pytest.fixture(autouse=True)
    def statuses(self, conn) -> None:
        conn.execute(text("UPDATE ml_items SET status = 'paused' WHERE item_id IN ('MLA5', 'MLA2')"))
        conn.execute(text("UPDATE ml_items SET status = NULL WHERE item_id = 'MLA3'"))
        seed.add_product(conn, 73, "D1", "Antena", marca="Ubiquiti", stock=1)
        seed.add_item(conn, "MLA6", status="closed")
        seed.add_item(conn, "MLA7", status="active", gone_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
        seed.add_link(conn, "MLA6", 73)
        seed.add_link(conn, "MLA7", 73)

    def test_lists_the_publications_of_products_with_no_active_publication(self, db) -> None:
        # 70 still has MLA1 active; 72's MLA3 has no status (active, as in Productos); MLA4 has no product;
        # 73's MLA7 is gone: not active, and hidden from the list as every gone publication is
        assert listed(db, estado_mla="pausada") == ["MLA2", "MLA6"]
        assert listed(db, estado_mla="pausada", estado="gone") == ["MLA7"]

    def test_ands_with_the_other_filters(self, db) -> None:
        assert listed(db, estado_mla="pausada", marcas="hikvision") == ["MLA2"]
