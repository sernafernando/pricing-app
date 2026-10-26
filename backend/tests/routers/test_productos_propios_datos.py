"""Publicaciones ML T7: editing the product's copied data. The title and description are free text; the pictures are
the copied ones, kept, dropped or reordered by id (no upload yet); the attributes are the copied ones, their values
edited or dropped. Editing needs a source chosen first.

Same harness as `test_productos_propios.py`.
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from tests.routers.test_productos_propios import BASE, editor, pg, product, read, reader  # noqa: F401
from tests.routers.test_productos_propios_fuente import COPIED, source, stored_data
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

EDIT = {
    "titulo": "  Router Archer AX55 WiFi 6  ",
    "descripcion": "Nueva descripción",
    "fotos": ["P2", "P1"],
    "atributos": [{"id": "MODEL", "value_name": " AX55 "}],
}


def edit(client, headers, body=None, item_id: int = 70):
    return client.put(f"{BASE}/{item_id}/datos", headers=headers, json=EDIT if body is None else body)


@pytest.fixture()
def copied(pg):
    """Product 70 with MLA1's data already copied (as `POST /fuente` stores it, see the fuente tests)."""
    with pg.begin() as conn:
        product(conn)
        source(conn)
        conn.execute(
            text(
                "INSERT INTO productos_propios (item_id, fuente_mla, titulo, descripcion, fotos, atributos, "
                "fuente_copiada_at) VALUES (70, :fuente_mla, :titulo, :descripcion, CAST(:fotos AS jsonb), "
                "CAST(:atributos AS jsonb), now())"
            ),
            {**COPIED, "fotos": json.dumps(COPIED["fotos"]), "atributos": json.dumps(COPIED["atributos"])},
        )
    return pg


class TestEdit:
    def test_saves_the_edit_reorders_pictures_and_keeps_the_source(self, client, copied, editor):
        response = edit(client, editor)

        assert response.status_code == 200, response.text
        datos = response.json()["datos"]
        assert datos["fuente_mla"] == "MLA1"
        assert (datos["titulo"], datos["descripcion"]) == ("Router Archer AX55 WiFi 6", "Nueva descripción")
        assert datos["fotos"] == [{"id": "P2", "url": "http://x/p2.webp"}, {"id": "P1", "url": "https://x/p1.webp"}]
        assert datos["atributos"] == [{"id": "MODEL", "name": "Modelo", "value_name": "AX55"}]
        assert stored_data(copied).titulo == "Router Archer AX55 WiFi 6"
        assert read(client, editor)["datos"] == datos

    def test_a_blank_description_and_no_pictures_or_attributes_are_kept_as_such(self, client, copied, editor):
        datos = edit(client, editor, {"titulo": "T", "descripcion": "  ", "fotos": [], "atributos": []}).json()["datos"]

        assert (datos["descripcion"], datos["fotos"], datos["atributos"]) == (None, [], [])

    def test_editing_keeps_the_manual_sku_and_ean(self, client, copied, editor):
        client.put(f"{BASE}/70", headers=editor, json={"sku": "MIO", "ean": "123"})

        body = edit(client, editor).json()

        assert (body["sku"], body["ean"]) == ("MIO", "123")


class TestEditRefused:
    def test_without_a_source_chosen_it_is_409(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        assert edit(client, editor).status_code == 409

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param({"fotos": ["P9"]}, id="a picture that was not copied"),
            pytest.param({"fotos": ["P1", "P1"]}, id="a repeated picture"),
            pytest.param(
                {"atributos": [{"id": "COLOR", "value_name": "Negro"}]}, id="an attribute that was not copied"
            ),
            pytest.param(
                {"atributos": [{"id": "MODEL", "value_name": "A"}, {"id": "MODEL", "value_name": "B"}]},
                id="a repeated attribute",
            ),
        ],
    )
    def test_pictures_and_attributes_must_be_the_copied_ones_once_each(self, client, copied, editor, change):
        response = edit(client, editor, {**EDIT, **change})

        assert response.status_code == 422, response.text
        assert stored_data(copied).titulo == "Router TP-Link Archer AX55"  # nothing saved

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param({"titulo": "   "}, id="blank title"),
            pytest.param({"titulo": "X" * 256}, id="title too long"),
            pytest.param({"descripcion": "X" * 50001}, id="description over ML's 50000"),
            pytest.param({"atributos": [{"id": "MODEL", "value_name": "  "}]}, id="blank attribute value"),
            pytest.param({"extra": 1}, id="unknown field"),
        ],
    )
    def test_a_malformed_body_is_422(self, client, copied, editor, change):
        assert edit(client, editor, {**EDIT, **change}).status_code == 422

    def test_a_missing_field_is_422(self, client, copied, editor):
        assert edit(client, editor, {k: v for k, v in EDIT.items() if k != "fotos"}).status_code == 422

    def test_editing_needs_the_edit_permission(self, client, copied, reader):
        assert edit(client, reader).status_code == 403

    def test_an_unknown_product_is_404(self, client, pg, editor):
        assert edit(client, editor, item_id=999).status_code == 404
