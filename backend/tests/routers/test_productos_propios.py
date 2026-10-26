"""Publicaciones ML T6: our own product, keyed by the ERP `item_id`, with an editable SKU and EAN.

Only manual values are stored (`productos_propios`); what the panel shows is computed on read: the EAN is the
manual one, else the ERP `codigo`; the SKU is the manual one, else the one SKU every live publication linked to the
product shares (none when they disagree: the candidates are listed instead). Same harness as the link router tests
(permissions in the SQLite test database, the store in a throwaway Postgres schema built from the real migrations).
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.routers import productos_propios
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

VER = "ml_ops.ver"
EDITAR = "ml_publicaciones.editar_producto"
BASE = "/api/productos-propios"


@pytest.fixture()
def pg(client, request):
    """The store behind the router. `client` goes first so the shared column types are Postgres' again."""
    engine = request.getfixturevalue("mlpub_pg")
    ProductoERP.__table__.create(bind=engine)
    ProductoPropio.__table__.create(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _store_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[productos_propios.get_productos_propios_db] = _store_db
    yield engine
    app.dependency_overrides.pop(productos_propios.get_productos_propios_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


def product(conn, item_id: int = 70, codigo: str = "7791234567890") -> None:
    seed.add_product(conn, item_id, codigo, f"Producto {item_id}")


def publication(conn, mla: str, producto: int, *, variation_id: int = 0, **item) -> None:
    """A live publication linked to `producto` (at item level, or through one of its variations)."""
    seed.add_item(conn, mla, **item)
    seed.add_link(conn, mla, producto, variation_id=variation_id)


def read(client, headers, item_id: int = 70) -> dict:
    response = client.get(f"{BASE}/{item_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def stored(engine, item_id: int = 70):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sku, ean, updated_by FROM productos_propios WHERE item_id = :i"), {"i": item_id}
        ).first()


class TestRead:
    def test_without_manual_values_the_ean_is_the_erp_codigo_and_the_sku_the_one_linked_publications_share(
        self, client, pg, reader
    ):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, seller_sku="TL-WR840N")
            publication(conn, "MLA2", 70, seller_custom_field="TL-WR840N")  # the custom field when no attribute

        body = read(client, reader)

        assert body["item_id"] == 70
        assert body["codigo"] == "7791234567890"
        assert body["ean"] == "7791234567890"
        assert body["ean_manual"] is False
        assert body["sku"] == "TL-WR840N"
        assert body["sku_manual"] is False
        assert body["sku_candidatos"] == ["TL-WR840N"]
        assert body["can_edit"] is False

    def test_linked_publications_that_disagree_leave_the_sku_empty_and_list_the_candidates(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, seller_sku="SKU-B")
            publication(conn, "MLA2", 70, seller_sku="SKU-A", seller_custom_field="IGNORED")  # the attribute wins
            publication(conn, "MLA3", 70)  # no SKU at all: not a candidate

        body = read(client, reader)

        assert body["sku"] is None
        assert body["sku_candidatos"] == ["SKU-A", "SKU-B"]

    def test_a_variation_link_reads_the_variation_sku(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, variation_id=11, seller_sku="ITEM-LEVEL")
            seed.add_variation(conn, "MLA1", 11, seller_sku="VAR-SKU")

        assert read(client, reader)["sku"] == "VAR-SKU"

    def test_deleted_publications_and_gone_variations_do_not_count(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, seller_sku="LIVE")
            publication(conn, "MLA2", 70, seller_sku="GONE", gone_at=seed.NOW)
            publication(conn, "MLA3", 70, seller_sku="DELETED", sub_status=["deleted"])
            publication(conn, "MLA4", 70, variation_id=12)
            seed.add_variation(conn, "MLA4", 12, seller_sku="GONE-VAR", gone_at=seed.NOW)
            publication(conn, "MLA5", 71, seller_sku="OTHER-PRODUCT")

        body = read(client, reader)

        assert body["sku"] == "LIVE"
        assert body["sku_candidatos"] == ["LIVE"]

    def test_manual_values_win_over_the_computed_ones(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, seller_sku="FROM-MLA")
            conn.execute(text("INSERT INTO productos_propios (item_id, sku, ean) VALUES (70, 'MANUAL', '123')"))

        body = read(client, reader)

        assert (body["sku"], body["sku_manual"]) == ("MANUAL", True)
        assert (body["ean"], body["ean_manual"]) == ("123", True)
        assert body["sku_candidatos"] == ["FROM-MLA"]  # still shown: the operator sees what the MLAs say

    def test_an_unknown_product_is_404(self, client, pg, reader):
        assert client.get(f"{BASE}/999", headers=reader).status_code == 404

    def test_reading_needs_the_view_permission(self, client, pg, admin_auth_headers):
        assert client.get(f"{BASE}/70", headers=admin_auth_headers).status_code == 403

    def test_the_editor_is_told_it_can_edit(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        assert read(client, editor)["can_edit"] is True


class TestEdit:
    def test_saves_trimmed_manual_values_with_who_saved_them(self, client, pg, editor, admin_user):
        with pg.begin() as conn:
            product(conn)

        response = client.put(f"{BASE}/70", headers=editor, json={"sku": "  MI-SKU ", "ean": " 779000 "})

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["sku"], body["sku_manual"], body["ean"], body["ean_manual"]) == ("MI-SKU", True, "779000", True)
        assert tuple(stored(pg)) == ("MI-SKU", "779000", admin_user.id)

    def test_the_length_limit_applies_to_the_trimmed_value(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        response = client.put(f"{BASE}/70", headers=editor, json={"sku": f"  {'X' * 100}  ", "ean": None})

        assert response.status_code == 200, response.text
        assert stored(pg).sku == "X" * 100

    def test_a_blank_or_null_value_drops_the_manual_one(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", 70, seller_sku="FROM-MLA")
            conn.execute(text("INSERT INTO productos_propios (item_id, sku, ean) VALUES (70, 'MANUAL', '123')"))

        body = client.put(f"{BASE}/70", headers=editor, json={"sku": "   ", "ean": "123"}).json()
        assert (body["sku"], body["sku_manual"]) == ("FROM-MLA", False)
        assert tuple(stored(pg))[:2] == (None, "123")

        body = client.put(f"{BASE}/70", headers=editor, json={"sku": None, "ean": None}).json()
        assert (body["ean"], body["ean_manual"]) == ("7791234567890", False)
        assert tuple(stored(pg))[:2] == (None, None)  # the row stays: it may hold the copied data (T7)

    def test_editing_needs_the_edit_permission(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)

        response = client.put(f"{BASE}/70", headers=reader, json={"sku": "X", "ean": None})

        assert response.status_code == 403
        assert stored(pg) is None

    def test_an_unknown_product_is_404_and_nothing_is_stored(self, client, pg, editor):
        response = client.put(f"{BASE}/999", headers=editor, json={"sku": "X", "ean": None})

        assert response.status_code == 404
        assert stored(pg, 999) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"sku": "X" * 101, "ean": None},  # longer than the ERP `codigo` column
            {"sku": "X"},  # both fields are required: a missing one is not "leave it as it is"
            {"sku": "X", "ean": None, "extra": 1},
        ],
    )
    def test_a_malformed_body_is_422(self, client, pg, editor, payload):
        with pg.begin() as conn:
            product(conn)

        assert client.put(f"{BASE}/70", headers=editor, json=payload).status_code == 422
        assert stored(pg) is None
