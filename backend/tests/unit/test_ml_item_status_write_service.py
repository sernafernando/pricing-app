"""`ml_item_status_write_service.set_item_status`: pause or activate one publication.

Order: kill switch -> the store's status (only a paused publication is activated, only an active one is paused;
a deleted one or one ML never reported is refused without calling ML) -> one write through the proxy -> on a
confirmed write, an `ml_write_log` row with the user -> a manual-lane refresh of the item, also after an ambiguous
write so the store learns what happened.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from app.models.ml_write_log import ACTION_ACTIVATE, ACTION_PAUSE, RESOURCE_ITEM, MlWriteLog
from app.models.usuario import Usuario
from app.services import ml_item_status_write_service as write_service
from app.services.ml_publication_status_service import GONE, NO_ML_DATA, MlPublicationStatus

MLA = "MLA123"


class FakeClient:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def put_item_status(self, item_id: str, status: str) -> dict:
        self.calls.append((item_id, status))
        return self.result


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch):
    """The store's status of MLA123, set per test."""
    current = {"value": MlPublicationStatus("active")}
    monkeypatch.setattr(write_service, "fetch_publication_status_by_mla", lambda db, ids: {MLA: current["value"]})
    return current


@pytest.fixture()
def ml(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient({"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": MLA}})
    monkeypatch.setattr(write_service, "MLWebhookClient", lambda: client)
    return client


@pytest.fixture()
def refreshed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    queued: list[str] = []
    monkeypatch.setattr(write_service, "_enqueue_refresh", queued.append)
    return queued


@pytest.fixture()
def bg_db(db, monkeypatch: pytest.MonkeyPatch):
    """Routes the service's short-lived `get_background_db()` to the test session (commit on exit, rollback +
    re-raise on an exception, like the real one)."""

    @contextmanager
    def _fake():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    monkeypatch.setattr(write_service, "get_background_db", _fake)
    return db


@pytest.fixture()
def usuario(db) -> Usuario:
    user = Usuario(username="status_writer", email="status_writer@example.com", nombre="Status Writer")
    db.add(user)
    db.flush()
    return user


def run(db, target: str, usuario_id=None) -> write_service.ItemStatusOutcome:
    return asyncio.run(write_service.set_item_status(db, MLA, target, usuario_id))


def logged(db) -> list[tuple]:
    return [(r.mla, r.resource, r.action, r.usuario_id) for r in db.query(MlWriteLog).order_by(MlWriteLog.id)]


def test_pauses_an_active_publication_and_logs_who_did_it(db, store, ml, refreshed, bg_db, usuario) -> None:
    outcome = run(db, "paused", usuario.id)
    assert outcome == write_service.ItemStatusOutcome(write_service.SUBMITTED, None)
    assert ml.calls == [(MLA, "paused")]
    assert logged(db) == [(MLA, RESOURCE_ITEM, ACTION_PAUSE, usuario.id)]
    assert refreshed == [MLA]


def test_activates_a_paused_publication(db, store, ml, refreshed, bg_db) -> None:
    store["value"] = MlPublicationStatus("paused", ["out_of_stock"])
    assert run(db, "active").status == write_service.SUBMITTED
    assert ml.calls == [(MLA, "active")]
    assert logged(db) == [(MLA, RESOURCE_ITEM, ACTION_ACTIVATE, None)]


def test_with_the_kill_switch_off_nothing_is_called(db, store, ml, refreshed, monkeypatch) -> None:
    monkeypatch.setattr(write_service.settings, "ML_ITEM_STATUS_WRITE_ENABLED", False)
    assert run(db, "paused").status == write_service.DISABLED
    assert ml.calls == [] and refreshed == []


def test_the_kill_switch_is_on_by_default() -> None:
    assert write_service.settings.model_fields["ML_ITEM_STATUS_WRITE_ENABLED"].default is True


@pytest.mark.parametrize(
    "current, target",
    [
        (MlPublicationStatus("closed"), "active"),
        (MlPublicationStatus("under_review", ["waiting_for_patch"]), "active"),
        (MlPublicationStatus("inactive"), "active"),
        (MlPublicationStatus("under_review"), "paused"),
        (MlPublicationStatus("closed"), "paused"),
        (MlPublicationStatus("inactive", ["forbidden", "deleted"]), "paused"),
        (MlPublicationStatus("paused", ["deleted"]), "active"),
        (MlPublicationStatus(GONE), "active"),
        (MlPublicationStatus(NO_ML_DATA), "paused"),
    ],
)
def test_a_publication_that_cannot_take_that_status_is_refused_without_calling_ml(
    db, store, ml, refreshed, current, target
) -> None:
    store["value"] = current
    outcome = run(db, target)
    assert outcome.status == write_service.NOT_ELIGIBLE and outcome.message
    assert ml.calls == [] and refreshed == []


def test_a_publication_already_in_that_status_is_not_written_but_refreshed(db, store, ml, refreshed) -> None:
    store["value"] = MlPublicationStatus("paused")
    assert run(db, "paused").status == write_service.UNCHANGED
    assert ml.calls == []
    assert refreshed == [MLA]  # the store may be stale: let it catch up


def test_an_ml_rejection_carries_its_message_and_logs_nothing(db, store, ml, refreshed, bg_db) -> None:
    ml.result = {"ok": False, "status_code": 400, "ambiguous": False, "body": {"message": "item has no stock"}}
    assert run(db, "paused") == write_service.ItemStatusOutcome(write_service.REJECTED, "item has no stock")
    assert logged(db) == [] and refreshed == []


def test_an_ambiguous_write_logs_nothing_and_refreshes_to_learn_what_happened(db, store, ml, refreshed, bg_db) -> None:
    ml.result = {"ok": False, "status_code": None, "ambiguous": True, "body": None}
    assert run(db, "paused").status == write_service.AMBIGUOUS
    assert logged(db) == []
    assert refreshed == [MLA]


def test_a_failing_log_or_refresh_never_turns_a_done_write_into_an_error(db, store, ml, monkeypatch) -> None:
    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    def broken_enqueue(*args, **kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(write_service, "get_background_db", broken)
    monkeypatch.setattr(write_service.ml_pub_queue, "enqueue", broken_enqueue)
    assert run(db, "paused").status == write_service.SUBMITTED


def test_the_refresh_is_a_manual_lane_core_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = []
    monkeypatch.setattr(write_service.ml_pub_queue, "enqueue", lambda batch, session=None: entries.extend(batch))
    write_service._enqueue_refresh(MLA)
    assert [(e.kind, e.entity_id, e.lane, e.resources) for e in entries] == [
        ("item", MLA, write_service.ml_pub_queue.LANE_MANUAL, (write_service.CORE_RESOURCE,))
    ]
