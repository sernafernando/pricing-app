"""Publicaciones ML T7: the product's data copied from one of its publications (title, description, pictures and
attributes), chosen in the product panel. A copy, not a live link: later edits of the product (T7 edit) and of the
publication do not touch each other. Catalog publications may be the source too (they are a base, not edited).

Same harness as `test_productos_propios.py`.
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from tests.routers.test_productos_propios import (  # noqa: F401
    BASE,
    editor,
    pg,
    product,
    publication,
    read,
    reader,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

RAW = {
    "title": "Router TP-Link Archer AX55 (raw)",
    "pictures": [
        {"id": "P1", "url": "http://x/p1.webp", "secure_url": "https://x/p1.webp", "size": "500x500"},
        {"id": "P2", "url": "http://x/p2.webp", "secure_url": None},
    ],
    "attributes": [
        {"id": "BRAND", "name": "Marca", "value_id": "1", "value_name": "TP-Link", "values": []},
        {"id": "COLOR", "name": "Color", "value_id": "-1", "value_name": None, "values": []},  # no value: skipped
        {"id": "MODEL", "name": "Modelo", "value_id": None, "value_name": "Archer AX55", "values": []},
    ],
}


def source(conn, mla: str = "MLA1", producto: int = 70, *, description: str | None = "Router WiFi 6", **item) -> None:
    """A live publication of `producto` with a captured body and, unless None, its stored description."""
    publication(conn, mla, producto, title="Router TP-Link Archer AX55", raw=json.dumps(RAW), **item)
    if description is not None:
        seed.add_state(
            conn, "ml_item_descriptions", "item_id", mla, raw=json.dumps({"text": "", "plain_text": description})
        )


def choose(client, headers, mla: str = "MLA1", item_id: int = 70):
    return client.post(f"{BASE}/{item_id}/fuente", headers=headers, json={"mla": mla})


def stored_data(engine, item_id: int = 70):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT fuente_mla, titulo, descripcion, fotos, atributos, fuente_copiada_por, fuente_copiada_at, "
                "sku, ean FROM productos_propios WHERE item_id = :i"
            ),
            {"i": item_id},
        ).first()


COPIED = {
    "fuente_mla": "MLA1",
    "titulo": "Router TP-Link Archer AX55",
    "descripcion": "Router WiFi 6",
    "fotos": [{"id": "P1", "url": "https://x/p1.webp"}, {"id": "P2", "url": "http://x/p2.webp"}],
    "atributos": [
        {"id": "BRAND", "name": "Marca", "value_name": "TP-Link"},
        {"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55"},
    ],
}


class TestChoose:
    def test_copies_title_description_pictures_and_attributes_and_answers_them(self, client, pg, editor, admin_user):
        with pg.begin() as conn:
            product(conn)
            source(conn)

        response = choose(client, editor)

        assert response.status_code == 200, response.text
        datos = response.json()["datos"]
        assert {key: datos[key] for key in COPIED} == COPIED
        assert datos["copiado_at"] is not None
        row = stored_data(pg)
        assert (row.fuente_mla, row.titulo, row.descripcion) == ("MLA1", COPIED["titulo"], COPIED["descripcion"])
        assert (row.fotos, row.atributos) == (COPIED["fotos"], COPIED["atributos"])
        assert row.fuente_copiada_por == admin_user.id

    def test_the_read_has_no_data_until_a_source_is_chosen_and_then_the_copy(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            source(conn)

        assert read(client, editor)["datos"] is None
        choose(client, editor)
        assert read(client, editor)["datos"]["fuente_mla"] == "MLA1"

    def test_a_publication_without_a_stored_description_copies_none(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            source(conn, description=None)

        assert choose(client, editor).json()["datos"]["descripcion"] is None

    def test_a_catalog_publication_may_be_the_source(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            source(conn, catalog_listing=True)

        assert choose(client, editor).status_code == 200

    def test_choosing_again_replaces_the_copy_and_keeps_the_manual_sku_and_ean(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            source(conn)
            publication(conn, "MLA2", 70, title="Otro título", raw=json.dumps({"pictures": [], "attributes": []}))
            conn.execute(text("INSERT INTO productos_propios (item_id, sku, ean) VALUES (70, 'MIO', '123')"))

        choose(client, editor)
        datos = choose(client, editor, "MLA2").json()["datos"]

        assert (datos["fuente_mla"], datos["titulo"], datos["descripcion"]) == ("MLA2", "Otro título", None)
        assert (datos["fotos"], datos["atributos"]) == ([], [])
        row = stored_data(pg)
        assert (row.sku, row.ean) == ("MIO", "123")

    def test_dropping_the_manual_sku_and_ean_keeps_the_copied_data(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            source(conn)
        choose(client, editor)

        response = client.put(f"{BASE}/70", headers=editor, json={"sku": None, "ean": None})

        assert response.status_code == 200, response.text
        assert response.json()["datos"]["fuente_mla"] == "MLA1"
        assert stored_data(pg).titulo == COPIED["titulo"]


class TestChooseRefused:
    @pytest.mark.parametrize(
        "seed_source",
        [
            pytest.param(lambda conn: source(conn, producto=71), id="linked to another product"),
            pytest.param(lambda conn: seed.add_item(conn, "MLA1", title="Sin vínculo"), id="not linked"),
            pytest.param(lambda conn: source(conn, gone_at=seed.NOW), id="gone"),
            pytest.param(lambda conn: source(conn, sub_status=["deleted"]), id="deleted at ML"),
        ],
    )
    def test_only_a_live_publication_of_the_product_is_409_free(self, client, pg, editor, seed_source):
        with pg.begin() as conn:
            product(conn)
            product(conn, 71, "7790000000071")
            seed_source(conn)

        response = choose(client, editor)

        assert response.status_code == 409, response.text
        assert stored_data(pg) is None

    def test_an_unknown_product_is_404(self, client, pg, editor):
        assert choose(client, editor, item_id=999).status_code == 404

    def test_choosing_needs_the_edit_permission(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            source(conn)

        assert choose(client, reader).status_code == 403
        assert stored_data(pg) is None

    @pytest.mark.parametrize("payload", [{"mla": "nope"}, {}, {"mla": "MLA1", "extra": 1}])
    def test_a_malformed_body_is_422(self, client, pg, editor, payload):
        with pg.begin() as conn:
            product(conn)

        assert client.post(f"{BASE}/70/fuente", headers=editor, json=payload).status_code == 422
