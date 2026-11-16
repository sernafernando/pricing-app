"""abm-productos S12: link a product to its Tienda Nube product by hand. The product page shows the current link
("Automático por SKU" or "Manual"), "Cambiar" searches the TN catalog with suggestions first (same EAN, compared
without leading 0 and without the `-OB` suffix, then a similar name), "Desvincular" stores a NULL link. A manual link
takes effect right away and survives every sync.

Permissions live in the SQLite test database; the product and TN tables in a throwaway Postgres schema.
"""

# ruff: noqa: F811 -- the fixtures are imported and used by name

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.routers import producto_tn_vinculos
from app.services.tienda_nube_sync_shared import sincronizar_catalogo
from tests.routers.test_ml_publications_links import grant
from tests.services.tienda_nube_pg import erp, links, tn_pg, tn_product  # noqa: F401

pytestmark = pytest.mark.postgres

VER = "productos.ver"
EDITAR = "productos.editar_maestro"
BASE = "/api/producto-tn-vinculos"


@pytest.fixture()
def pg(client, tn_pg):
    factory = sessionmaker(bind=tn_pg, autocommit=False, autoflush=False)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[producto_tn_vinculos.get_producto_tn_db] = _db
    yield tn_pg
    app.dependency_overrides.pop(producto_tn_vinculos.get_producto_tn_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


def catalog(engine, products: list[dict]) -> None:
    with Session(engine) as db:
        sincronizar_catalogo(db, products, fetch_complete=True)
        db.commit()


def seed(engine) -> None:
    with engine.begin() as conn:
        erp(conn, 10, "7790001", "NB LENOVO V15 G5 IRL I7-13620H 16GB")
        erp(conn, 20, "0455", "MOUSE LOGITECH UB500")
    catalog(
        engine,
        [
            tn_product(1, "Notebook Lenovo V15 G5 i7", ["7790001"], price="1500000.00"),
            tn_product(2, "Notebook Lenovo V15 G5 i7 caja abierta", ["7790001-OB"], published=False),
            tn_product(3, "Mouse Logitech UB500", ["455"]),
        ],
    )


def get(client, headers, item_id: int) -> dict:
    response = client.get(f"{BASE}/{item_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestCurrentLink:
    def test_a_sku_match_shows_as_automatic(self, client, pg, reader):
        seed(pg)

        body = get(client, reader, 10)

        assert body["origen"] == "sku"
        assert body["tn"] == {
            "tn_product_id": 1,
            "nombre": "Notebook Lenovo V15 G5 i7",
            "skus": ["7790001"],
            "precio": 1500000.0,
            "published": True,
            "item_id": 10,
        }
        assert body["can_edit"] is False

    def test_an_unlinked_product_has_no_link(self, client, pg, reader):
        with pg.begin() as conn:
            erp(conn, 30, "999", "SIN TN")

        body = get(client, reader, 30)

        assert body["origen"] is None and body["tn"] is None

    def test_an_unknown_product_is_404(self, client, pg, reader):
        assert client.get(f"{BASE}/404", headers=reader).status_code == 404


class TestChange:
    def test_a_manual_link_takes_effect_now_and_survives_the_next_sync(self, client, pg, editor):
        seed(pg)

        response = client.put(f"{BASE}/10", headers=editor, json={"tn_product_id": 2})

        assert response.status_code == 200, response.text
        assert response.json()["origen"] == "manual"
        assert response.json()["tn"]["tn_product_id"] == 2
        with pg.connect() as conn:
            assert links(conn)[1] is None and links(conn)[2] == 10
        seed_again = [
            tn_product(1, "Notebook Lenovo V15 G5 i7", ["7790001"]),
            tn_product(2, "Notebook Lenovo V15 G5 i7 caja abierta", ["7790001-OB"]),
            tn_product(3, "Mouse Logitech UB500", ["455"]),
        ]
        catalog(pg, seed_again)
        with pg.connect() as conn:
            assert links(conn) == {1: None, 2: 10, 3: 20}
        assert get(client, editor, 10)["origen"] == "manual"

    def test_unlinking_stores_a_null_link_that_the_sync_respects(self, client, pg, editor):
        seed(pg)

        response = client.put(f"{BASE}/10", headers=editor, json={"tn_product_id": None})

        assert response.status_code == 200, response.text
        assert response.json()["origen"] == "manual" and response.json()["tn"] is None
        with pg.connect() as conn:
            assert links(conn)[1] is None
            stored = conn.execute(text("SELECT tn_product_id, updated_by FROM producto_tn_vinculos")).one()
        assert stored[0] is None and stored[1] is not None

    def test_a_tn_product_already_linked_by_hand_to_another_product_is_refused(self, client, pg, editor):
        seed(pg)
        assert client.put(f"{BASE}/10", headers=editor, json={"tn_product_id": 3}).status_code == 200

        response = client.put(f"{BASE}/20", headers=editor, json={"tn_product_id": 3})

        assert response.status_code == 409
        assert "10" in response.json()["error"]["message"]

    def test_an_unknown_tn_product_is_404(self, client, pg, editor):
        seed(pg)
        assert client.put(f"{BASE}/10", headers=editor, json={"tn_product_id": 999}).status_code == 404

    def test_changing_needs_the_master_edit_permission(self, client, pg, reader):
        seed(pg)
        assert client.put(f"{BASE}/10", headers=reader, json={"tn_product_id": 2}).status_code == 403

    def test_reading_needs_productos_ver(self, client, pg, admin_auth_headers):
        seed(pg)
        assert client.get(f"{BASE}/10", headers=admin_auth_headers).status_code == 403


class TestCandidates:
    def test_suggestions_are_the_same_ean_first_ignoring_leading_zero_and_ob_then_a_similar_name(
        self, client, pg, reader
    ):
        seed(pg)
        with pg.begin() as conn:
            erp(conn, 40, "8880001", "NOTEBOOK LENOVO V15 RYZEN")
        catalog(
            pg,
            [
                tn_product(1, "Notebook Lenovo V15 G5 i7", ["7790001"]),
                tn_product(2, "Notebook Lenovo V15 G5 i7 caja abierta", ["7790001-OB"]),
                tn_product(3, "Mouse Logitech UB500", ["455"]),
                tn_product(4, "Notebook Lenovo V15 Ryzen 5", ["8880099"]),
            ],
        )

        mouse = client.get(f"{BASE}/20/candidatos", headers=reader).json()
        notebook = client.get(f"{BASE}/40/candidatos", headers=reader).json()

        assert [(c["tn_product_id"], c["motivo"]) for c in mouse][:1] == [(3, "ean")]
        assert notebook[0]["tn_product_id"] == 4 and notebook[0]["motivo"] == "nombre"

    def test_the_ob_variant_is_suggested_by_ean_for_the_base_product(self, client, pg, reader):
        seed(pg)

        candidates = client.get(f"{BASE}/10/candidatos", headers=reader).json()

        assert {(c["tn_product_id"], c["motivo"]) for c in candidates if c["motivo"] == "ean"} == {
            (1, "ean"),
            (2, "ean"),
        }

    def test_a_search_matches_name_or_sku(self, client, pg, reader):
        seed(pg)

        by_name = client.get(f"{BASE}/10/candidatos", headers=reader, params={"q": "ub500"}).json()
        by_sku = client.get(f"{BASE}/10/candidatos", headers=reader, params={"q": "7790001-OB"}).json()

        assert [(c["tn_product_id"], c["motivo"]) for c in by_name] == [(3, "busqueda")]
        assert [c["tn_product_id"] for c in by_sku] == [2]
        assert by_name[0]["item_id"] == 20  # who holds it today, so the screen can warn before moving it
