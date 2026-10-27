"""`ml_item_override_push_service`: push a publication's local override to ML ("Actualizar en ML", Publicaciones ML T8c).

The owner's rule (L20): editing never writes ML; pushing is a separate button, "no siempre se puede modificar en ml".
So `plan_push` sends only what differs from ML's data AND what ML lets change, and names every field it leaves out
with the reason; `push_override` checks the kill switch first, then writes the item fields and the description
through the proxy (one call each, never retried), logs each confirmed write with the user, and re-reads the item.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from app.models.ml_write_log import ACTION_UPDATE_DATA, ACTION_UPDATE_DESCRIPTION, RESOURCE_ITEM, MlWriteLog
from app.models.usuario import Usuario
from app.services import ml_item_override_push_service as push
from app.services.ml_item_override_push_service import Parte, PushFacts, plan_push

MLA = "MLA123"
ORIGINAL = {
    "titulo": "Router TP-Link Archer AX55",
    "descripcion": "Router WiFi 6",
    "fotos": [{"id": "P1", "url": "https://x/p1"}, {"id": "P2", "url": "https://x/p2"}],
    "atributos": [
        {"id": "BRAND", "name": "Marca", "value_name": "TP-Link"},
        {"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55"},
    ],
}
NOTHING = {"titulo": None, "descripcion": None, "fotos": None, "atributos": None}
LIVE = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False)


def override(**fields) -> dict:
    return {**NOTHING, **fields}


# ── plan_push: what ML lets change ──────────────────────────────────


def test_the_title_goes_when_the_publication_has_no_sales() -> None:
    plan = plan_push(LIVE, ORIGINAL, override(titulo="Router AX55 WiFi 6"))
    assert (plan.refused, plan.item_body, plan.descripcion, plan.omitidos) == (
        None,
        {"title": "Router AX55 WiFi 6"},
        None,
        (),
    )


def test_the_title_is_left_out_once_the_publication_sold() -> None:
    facts = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=3, has_variations=False)
    plan = plan_push(facts, ORIGINAL, override(titulo="Otro", descripcion="Nueva"))
    assert plan.item_body == {}
    assert plan.descripcion == "Nueva"
    assert plan.omitidos == (("titulo", "La publicación tiene ventas: Mercado Libre no deja cambiar el título."),)


def test_pictures_go_as_ids_in_the_new_order_unless_there_are_variations() -> None:
    reordered = override(fotos=[ORIGINAL["fotos"][1]])
    assert plan_push(LIVE, ORIGINAL, reordered).item_body == {"pictures": [{"id": "P2"}]}
    facts = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=True)
    plan = plan_push(facts, ORIGINAL, reordered)
    assert plan.item_body == {}
    assert plan.omitidos == (
        ("fotos", "La publicación tiene variaciones: las fotos se cambian en Mercado Libre, por variación."),
    )


def test_only_changed_attribute_values_go_and_a_dropped_attribute_is_not_deleted() -> None:
    kept = [{"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55 Pro"}]
    plan = plan_push(LIVE, ORIGINAL, override(atributos=kept))
    assert plan.item_body == {"attributes": [{"id": "MODEL", "value_name": "Archer AX55 Pro"}]}
    assert plan.omitidos == (("atributos", "Los atributos quitados no se borran en Mercado Libre: Marca."),)


def test_a_blank_description_is_left_out() -> None:
    plan = plan_push(LIVE, ORIGINAL, override(descripcion=""))
    assert plan.descripcion is None
    assert plan.omitidos == (("descripcion", "Mercado Libre no acepta una descripción vacía."),)


def test_fields_equal_to_ml_are_not_sent() -> None:
    same = override(titulo=ORIGINAL["titulo"], descripcion=ORIGINAL["descripcion"], fotos=ORIGINAL["fotos"])
    plan = plan_push(LIVE, ORIGINAL, same)
    assert (plan.item_body, plan.descripcion, plan.omitidos) == ({}, None, ())


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (
            PushFacts(status="active", deleted=False, catalog_listing=True, sold_quantity=0, has_variations=False),
            "Las publicaciones de catálogo no se pueden modificar en Mercado Libre.",
        ),
        (
            PushFacts(status="closed", deleted=True, catalog_listing=False, sold_quantity=0, has_variations=False),
            "La publicación está eliminada.",
        ),
        (
            PushFacts(
                status="under_review", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False
            ),
            "Una publicación en estado under_review no se puede modificar.",
        ),
    ],
)
def test_a_publication_ml_does_not_let_modify_is_refused(facts: PushFacts, reason: str) -> None:
    assert plan_push(facts, ORIGINAL, override(titulo="Otro")).refused == reason


def test_a_paused_publication_can_be_modified() -> None:
    facts = PushFacts(status="paused", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False)
    assert plan_push(facts, ORIGINAL, override(titulo="Otro")).item_body == {"title": "Otro"}


# ── push_override: the write ────────────────────────────────────────


class FakeClient:
    def __init__(self) -> None:
        self.data = {"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": MLA}}
        self.description = {"ok": True, "status_code": 200, "ambiguous": False, "body": {}}
        self.calls: list[tuple] = []

    async def put_item_data(self, item_id: str, body: dict) -> dict:
        self.calls.append(("data", item_id, body))
        return self.data

    async def put_item_description(self, item_id: str, plain_text: str) -> dict:
        self.calls.append(("description", item_id, plain_text))
        return self.description


@pytest.fixture()
def stored(monkeypatch: pytest.MonkeyPatch) -> dict:
    """What the store answers for MLA123; `value` None is a read that failed, `found` False an unknown MLA."""
    current = {
        "value": push.Stored(
            found=True, facts=LIVE, original=ORIGINAL, override=override(titulo="Nuevo", descripcion="Otra")
        )
    }
    monkeypatch.setattr(push, "_read", lambda mla: current["value"])
    return current


@pytest.fixture()
def ml(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(push, "MLWebhookClient", lambda: client)
    return client


@pytest.fixture()
def refreshed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    queued: list[str] = []
    monkeypatch.setattr(push, "_enqueue_refresh", queued.append)
    return queued


@pytest.fixture()
def bg_db(db, monkeypatch: pytest.MonkeyPatch):
    @contextmanager
    def _fake():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    monkeypatch.setattr(push, "get_background_db", _fake)
    return db


@pytest.fixture()
def usuario(db) -> Usuario:
    user = Usuario(username="data_writer", email="data_writer@example.com", nombre="Data Writer")
    db.add(user)
    db.flush()
    return user


def run(usuario_id=None) -> push.PushOutcome:
    return asyncio.run(push.push_override(MLA, usuario_id))


def logged(db) -> list[tuple]:
    return [(r.resource, r.action, r.payload, r.usuario_id) for r in db.query(MlWriteLog).order_by(MlWriteLog.id)]


def test_pushes_the_item_fields_and_the_description_and_logs_each(db, stored, ml, refreshed, bg_db, usuario) -> None:
    outcome = run(usuario.id)
    assert outcome.status == push.SENT
    assert outcome.partes == (Parte("titulo", push.SUBMITTED, None), Parte("descripcion", push.SUBMITTED, None))
    assert ml.calls == [("data", MLA, {"title": "Nuevo"}), ("description", MLA, "Otra")]
    assert logged(db) == [
        (RESOURCE_ITEM, ACTION_UPDATE_DATA, {"title": "Nuevo"}, usuario.id),
        (RESOURCE_ITEM, ACTION_UPDATE_DESCRIPTION, {"plain_text": "Otra"}, usuario.id),
    ]
    assert refreshed == [MLA]


def test_with_the_kill_switch_off_nothing_is_read_or_sent(stored, ml, refreshed, monkeypatch) -> None:
    monkeypatch.setattr(push.settings, "ML_ITEM_DATA_WRITE_ENABLED", False)
    stored["value"] = "must not be read"
    outcome = run()
    assert (outcome.status, ml.calls, refreshed) == (push.DISABLED, [], [])


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (None, push.UNKNOWN_STATUS),
        (push.Stored(found=False, facts=None, original=None, override=None), push.NOT_FOUND),
        (push.Stored(found=True, facts=LIVE, original=ORIGINAL, override=None), push.NOTHING),
        (
            push.Stored(
                found=True,
                facts=PushFacts(
                    status="active", deleted=False, catalog_listing=True, sold_quantity=0, has_variations=False
                ),
                original=ORIGINAL,
                override=override(titulo="Otro"),
            ),
            push.NOT_ELIGIBLE,
        ),
    ],
)
def test_nothing_reaches_ml_when_there_is_nothing_it_would_take(stored, ml, refreshed, value, status) -> None:
    stored["value"] = value
    assert run().status == status
    assert (ml.calls, refreshed) == ([], [])


def test_only_left_out_fields_send_nothing_but_say_why(stored, ml, refreshed) -> None:
    sold = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=1, has_variations=False)
    stored["value"] = push.Stored(found=True, facts=sold, original=ORIGINAL, override=override(titulo="Otro"))
    outcome = run()
    assert outcome.status == push.NOTHING
    assert outcome.partes == (
        Parte("titulo", push.OMITTED, "La publicación tiene ventas: Mercado Libre no deja cambiar el título."),
    )
    assert ml.calls == []


def test_an_ml_rejection_and_an_unknown_outcome_are_reported_per_field(db, stored, ml, refreshed, bg_db) -> None:
    ml.data = {"ok": False, "status_code": 400, "ambiguous": False, "body": {"message": "title not modifiable"}}
    ml.description = {"ok": False, "status_code": None, "ambiguous": True, "body": None}
    outcome = run()
    assert outcome.status == push.SENT
    assert outcome.partes == (
        Parte("titulo", push.REJECTED, "title not modifiable"),
        Parte("descripcion", push.AMBIGUOUS, "No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar."),
    )
    assert logged(db) == []
    assert refreshed == [MLA]


def test_a_write_the_proxy_did_not_send_is_not_sent(db, stored, ml, refreshed, bg_db) -> None:
    ml.data = {"ok": False, "status_code": 503, "ambiguous": False, "body": {"data_write": "not_attempted"}}
    ml.description = {
        "ok": False,
        "status_code": 503,
        "ambiguous": False,
        "body": {"description_write": "not_attempted"},
    }
    outcome = run()
    assert [parte.estado for parte in outcome.partes] == [push.NOT_SENT, push.NOT_SENT]
    assert refreshed == []
