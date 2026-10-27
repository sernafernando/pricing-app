"""Publicaciones ML T8: a publication's data overridden locally, never written to ML by the edit.

The override is stored per MLA, field by field (a field left out follows ML); the original is what ML has (the last
read of the publication). Every read carries both, plus the applicable data (the override where there is one, else
the original), so a later reader (an export to another marketplace) can show either. Pushing the override to ML is a
separate action (T8c). Same harness as `test_productos_propios.py`.
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.ml_item_override import MlItemOverride
from app.routers import ml_item_overrides
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_productos_propios_fuente import RAW
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

VER = "ml_ops.ver"
EDITAR = "ml_publicaciones.editar_publicacion"
BASE = "/api/ml-item-overrides"

ORIGINAL = {
    "titulo": "Router TP-Link Archer AX55",
    "descripcion": "Router WiFi 6",
    "fotos": [{"id": "P1", "url": "https://x/p1.webp"}, {"id": "P2", "url": "http://x/p2.webp"}],
    "atributos": [
        {"id": "BRAND", "name": "Marca", "value_name": "TP-Link"},
        {"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55"},
    ],
}
NOTHING = {"titulo": None, "descripcion": None, "fotos": None, "atributos": None}


@pytest.fixture()
def pg(client, request):
    """The store behind the router. `client` goes first so the shared column types are Postgres' again."""
    engine = request.getfixturevalue("mlpub_pg")
    MlItemOverride.__table__.create(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _store_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[ml_item_overrides.get_ml_item_overrides_db] = _store_db
    yield engine
    app.dependency_overrides.pop(ml_item_overrides.get_ml_item_overrides_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


def publication(conn, mla: str = "MLA1", *, description: str | None = "Router WiFi 6", **item) -> None:
    """A publication with a captured body and, unless None, its stored description."""
    seed.add_item(conn, mla, title="Router TP-Link Archer AX55", raw=json.dumps(RAW), **item)
    if description is not None:
        seed.add_state(
            conn, "ml_item_descriptions", "item_id", mla, raw=json.dumps({"text": "", "plain_text": description})
        )


def read(client, headers, mla: str = "MLA1") -> dict:
    response = client.get(f"{BASE}/{mla}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def save(client, headers, mla: str = "MLA1", **fields):
    return client.put(f"{BASE}/{mla}", headers=headers, json={**NOTHING, **fields})


def stored(engine, mla: str = "MLA1"):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT titulo, descripcion, fotos, atributos, updated_by FROM ml_item_overrides WHERE item_id = :i"),
            {"i": mla},
        ).first()


class TestRead:
    def test_without_an_override_the_applicable_data_is_the_original(self, client, pg, reader):
        with pg.begin() as conn:
            publication(conn)

        body = read(client, reader)

        assert body["item_id"] == "MLA1"
        assert body["original"] == ORIGINAL
        assert body["override"] is None
        assert body["aplicado"] == ORIGINAL
        assert body["editable"] is True
        assert body["can_edit"] is False

    def test_a_publication_without_a_stored_description_has_none(self, client, pg, reader):
        with pg.begin() as conn:
            publication(conn, description=None)

        assert read(client, reader)["original"]["descripcion"] is None

    def test_an_unknown_publication_is_404(self, client, pg, reader):
        assert client.get(f"{BASE}/MLA9", headers=reader).status_code == 404

    def test_a_deleted_publication_reads_but_is_not_editable(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn, sub_status=["deleted"])

        body = read(client, editor)

        assert body["editable"] is False
        assert body["can_edit"] is True

    def test_needs_ml_ops_ver(self, client, pg, admin_auth_headers):
        with pg.begin() as conn:
            publication(conn)

        assert client.get(f"{BASE}/MLA1", headers=admin_auth_headers).status_code == 403


class TestSave:
    def test_overrides_the_title_and_keeps_the_original_beside_it(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)

        response = save(client, editor, titulo="Router AX55 Wi-Fi 6")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["original"] == ORIGINAL
        assert body["override"] == {**NOTHING, "titulo": "Router AX55 Wi-Fi 6"}
        assert body["aplicado"] == {**ORIGINAL, "titulo": "Router AX55 Wi-Fi 6"}
        assert body["can_edit"] is True
        assert read(client, editor) == body
        assert stored(pg).titulo == "Router AX55 Wi-Fi 6"

    def test_a_blank_description_overrides_with_none_and_null_follows_ml(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)

        body = save(client, editor, descripcion="   ").json()

        assert body["override"]["descripcion"] == ""
        assert body["aplicado"]["descripcion"] is None
        assert body["original"]["descripcion"] == "Router WiFi 6"

    def test_pictures_and_attributes_keep_the_original_ones_named_in_the_new_order_and_values(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)

        body = save(
            client,
            editor,
            fotos=["P2"],
            atributos=[{"id": "MODEL", "value_name": "AX55"}, {"id": "BRAND", "value_name": "TP-Link"}],
        ).json()

        assert body["override"]["fotos"] == [{"id": "P2", "url": "http://x/p2.webp"}]
        assert body["override"]["atributos"] == [
            {"id": "MODEL", "name": "Modelo", "value_name": "AX55"},
            {"id": "BRAND", "name": "Marca", "value_name": "TP-Link"},
        ]
        assert body["aplicado"]["fotos"] == body["override"]["fotos"]
        assert body["aplicado"]["titulo"] == ORIGINAL["titulo"]  # not overridden: follows ML

    def test_a_field_not_overridden_follows_ml_when_ml_changes(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)
        save(client, editor, titulo="Mío")
        with pg.begin() as conn:
            conn.execute(
                text("UPDATE ml_item_descriptions SET raw = CAST(:r AS jsonb) WHERE item_id = 'MLA1'"),
                {"r": json.dumps({"plain_text": "Nueva de ML"})},
            )

        body = read(client, editor)

        assert body["aplicado"]["descripcion"] == "Nueva de ML"
        assert body["aplicado"]["titulo"] == "Mío"

    def test_a_picture_ml_dropped_later_stays_in_the_override_and_can_be_saved_again(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)
        save(client, editor, fotos=["P1", "P2"])
        with pg.begin() as conn:
            raw = {**RAW, "pictures": RAW["pictures"][1:]}
            conn.execute(
                text("UPDATE ml_items SET raw = CAST(:r AS jsonb) WHERE item_id = 'MLA1'"), {"r": json.dumps(raw)}
            )

        response = save(client, editor, fotos=["P2", "P1"])

        assert response.status_code == 200, response.text
        assert [foto["id"] for foto in response.json()["aplicado"]["fotos"]] == ["P2", "P1"]

    def test_every_field_null_drops_the_override(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn)
        save(client, editor, titulo="Mío")

        body = save(client, editor).json()

        assert body["override"] is None
        assert body["aplicado"] == ORIGINAL
        assert stored(pg) is None

    @pytest.mark.parametrize(
        "fields",
        [
            {"fotos": ["P9"]},
            {"fotos": ["P1", "P1"]},
            {"atributos": [{"id": "COLOR", "value_name": "Negro"}]},  # copied without a value: not an original one
            {"atributos": [{"id": "BRAND", "value_name": "A"}, {"id": "BRAND", "value_name": "B"}]},
        ],
    )
    def test_a_picture_or_attribute_that_is_not_the_publications_or_is_repeated_is_422(
        self, client, pg, editor, fields
    ):
        with pg.begin() as conn:
            publication(conn)

        response = save(client, editor, **fields)

        assert response.status_code == 422
        assert response.json()["error"]["message"]  # the reason, in words, in the app's error envelope
        assert stored(pg) is None

    @pytest.mark.parametrize(
        "fields",
        [{"titulo": "   "}, {"titulo": "x" * 256}, {"atributos": [{"id": "BRAND", "value_name": " "}]}, {"otro": 1}],
    )
    def test_a_blank_or_too_long_value_or_an_unknown_field_is_422(self, client, pg, editor, fields):
        with pg.begin() as conn:
            publication(conn)

        assert save(client, editor, **fields).status_code == 422

    def test_a_deleted_publication_is_409(self, client, pg, editor):
        with pg.begin() as conn:
            publication(conn, gone_at="2026-10-20T00:00:00Z")

        response = save(client, editor, titulo="Mío")

        assert response.status_code == 409
        assert stored(pg) is None

    def test_an_unknown_publication_is_404(self, client, pg, editor):
        assert save(client, editor, "MLA9", titulo="Mío").status_code == 404

    def test_needs_the_edit_permission(self, client, pg, reader):
        with pg.begin() as conn:
            publication(conn)

        assert save(client, reader, titulo="Mío").status_code == 403
        assert stored(pg) is None


class TestPushRead:
    """What "Actualizar en ML" (T8c) reads from the store before deciding: ML's rules' facts, the original and the
    override, on its own short session."""

    @pytest.fixture()
    def push_db(self, pg, monkeypatch):
        from contextlib import contextmanager

        from app.services import ml_item_override_push_service as push

        @contextmanager
        def session():
            with Session(pg) as db:
                yield db

        monkeypatch.setattr(push, "get_background_db", session)
        return push

    def test_reads_the_facts_the_original_and_the_override(self, client, pg, editor, push_db):
        with pg.begin() as conn:
            publication(conn, status="paused", sold_quantity=4, catalog_listing=False)
            seed.add_variation(conn, "MLA1", 11)
        assert save(client, editor, titulo="Router AX55").status_code == 200

        stored_now = push_db._read("MLA1")

        assert stored_now.found is True
        assert stored_now.facts == push_db.PushFacts(
            status="paused", deleted=False, catalog_listing=False, sold_quantity=4, has_variations=True
        )
        assert stored_now.original == ORIGINAL
        assert stored_now.override == {**NOTHING, "titulo": "Router AX55"}

    def test_a_deleted_publication_and_an_unknown_one(self, pg, push_db):
        with pg.begin() as conn:
            publication(conn, status="closed", sub_status=["deleted"])

        assert push_db._read("MLA1").facts.deleted is True
        assert push_db._read("MLA9") == push_db.Stored(False, None, None, None)
