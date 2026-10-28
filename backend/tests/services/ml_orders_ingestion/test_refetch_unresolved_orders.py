"""remove-ml-divergences D2c: the quarantine retry asks ML again for the orders it never gave back.

A payload-less quarantine row (`has_no_payload`) is an order the activity receiver could not fetch. Each due row is
fetched again, with the HTTP outside the DB session:
  - ML gives the order back: it is written through the replay's own path, in the same pass;
  - ML says the order does not exist (404 `not_found`): the row is deleted, with one log line;
  - anything else (timeout, 5xx, a proxy error): the attempt is counted and the row waits for its backoff, with no cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.ml_orders_ops import MlOrdersOps, MlOrdersOpsCuarentena
from app.services.ml_orders_ingestion import activity_receiver_service as service
from app.services.ml_orders_ingestion import ingestion_service
from app.services.ml_webhook_client import OrderFetch, ml_webhook_client

LONG_AGO = timedelta(days=2)


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    monkeypatch.setattr(service, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(ingestion_service, "congelar", lambda db, order_id, items: None)


def _order(order_id: int) -> dict:
    """The `/orders/<id>` shape (`last_updated`, not `date_last_updated`; see test_activity_receiver_service)."""
    when = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {
        "id": order_id,
        "status": "paid",
        "date_created": when,
        "last_updated": when,
        "seller": {"id": 999},
        "buyer": {"id": 1, "nickname": "x"},
        "order_items": [],
    }


def _miss(db, order_id: int, ago: timedelta = LONG_AGO, intentos: int = 1, raw_order=None) -> None:
    last = datetime.now(timezone.utc) - ago
    db.add(
        MlOrdersOpsCuarentena(
            order_id=order_id,
            raw_order=raw_order,
            error=service.UNRESOLVED_ERROR,
            intentos=intentos,
            primera_falla_at=last,
            ultimo_intento_at=last,
        )
    )
    db.commit()


def _row(db, order_id: int):
    db.expire_all()
    return db.query(MlOrdersOpsCuarentena).filter_by(order_id=order_id).one_or_none()


def _ml_answers(monkeypatch, answers: dict) -> AsyncMock:
    mock = AsyncMock(side_effect=lambda order_id: answers[order_id])
    monkeypatch.setattr(ml_webhook_client, "fetch_order", mock)
    return mock


class TestTheRefetch:
    def test_an_order_ml_gives_back_lands_in_the_same_pass(self, db, monkeypatch):
        _miss(db, 501)
        _ml_answers(monkeypatch, {501: OrderFetch("ok", _order(501))})

        result = service.refetch_unresolved_orders()

        assert (result.attempted, result.landed, result.dropped, result.failed) == (1, 1, 0, 0)
        assert _row(db, 501) is None
        assert db.query(MlOrdersOps).filter_by(order_id=501).count() == 1

    def test_an_order_that_comes_back_but_does_not_map_is_quarantined_with_its_payload(self, db, monkeypatch):
        """The replay's own path: a payload that does not map is a permanent failure, kept for the replay."""
        _miss(db, 508)
        broken = {"id": 508, "status": "paid"}
        _ml_answers(monkeypatch, {508: OrderFetch("ok", broken)})

        result = service.refetch_unresolved_orders()

        assert (result.landed, result.failed) == (0, 1)
        row = _row(db, 508)
        assert row.raw_order == broken
        assert row.error.startswith(ingestion_service.PERMANENT_TAG + "mapping error on retry")
        assert row.intentos == 2

    def test_an_order_ml_does_not_have_is_deleted_with_one_log_line(self, db, monkeypatch, caplog):
        _miss(db, 502)
        _ml_answers(monkeypatch, {502: OrderFetch("not_found")})

        with caplog.at_level("WARNING"):
            result = service.refetch_unresolved_orders()

        assert (result.attempted, result.landed, result.dropped, result.failed) == (1, 0, 1, 0)
        assert _row(db, 502) is None
        assert [r for r in caplog.records if "502" in r.getMessage()] != []

    def test_a_failed_fetch_counts_the_attempt_and_waits_for_its_backoff(self, db, monkeypatch):
        _miss(db, 503, intentos=40)  # far past any permanent cap: a transient miss is never capped
        _ml_answers(monkeypatch, {503: OrderFetch("error")})

        result = service.refetch_unresolved_orders()

        assert (result.attempted, result.landed, result.dropped, result.failed) == (1, 0, 0, 1)
        row = _row(db, 503)
        assert row.raw_order is None
        assert row.intentos == 41
        assert row.error == service.UNRESOLVED_ERROR
        assert row.ultimo_intento_at is not None

        # Inside its backoff now: the next pass does not ask ML again.
        assert service.refetch_unresolved_orders().attempted == 0

    def test_a_fetch_that_raises_is_a_failed_fetch(self, db, monkeypatch):
        _miss(db, 504)
        monkeypatch.setattr(ml_webhook_client, "fetch_order", AsyncMock(side_effect=RuntimeError("boom")))

        result = service.refetch_unresolved_orders()

        assert result.failed == 1
        assert _row(db, 504).intentos == 2

    def test_a_row_the_old_replay_tagged_permanent_is_still_fetched(self, db, monkeypatch):
        """Verifier #1818 A3: during the deploy the old worker replays a copied row, stores the JSON `null` literal and
        tags it `[permanent]`, attempts >= 2. It is still a payload-less row: no permanent cap applies to it, and a
        failed fetch puts it back on the transient tag."""
        _miss(db, 509, intentos=7)
        db.execute(
            text("UPDATE ml_orders_ops_cuarentena SET raw_order = 'null', error = :e WHERE order_id = 509"),
            {"e": ingestion_service.PERMANENT_TAG + "mapping error on retry: no id"},
        )
        db.commit()
        _ml_answers(monkeypatch, {509: OrderFetch("error")})

        assert service.refetch_unresolved_orders().attempted == 1
        row = _row(db, 509)
        assert row.intentos == 8
        assert row.error == service.UNRESOLVED_ERROR

    def test_a_row_inside_its_backoff_is_not_fetched(self, db, monkeypatch):
        _miss(db, 505, ago=timedelta(seconds=5))
        mock = _ml_answers(monkeypatch, {})

        assert service.refetch_unresolved_orders().attempted == 0
        mock.assert_not_called()

    def test_a_row_with_a_payload_is_never_fetched(self, db, monkeypatch):
        _miss(db, 506, raw_order={"id": 506})
        mock = _ml_answers(monkeypatch, {})

        assert service.refetch_unresolved_orders().attempted == 0
        mock.assert_not_called()

    def test_a_payload_that_arrived_during_the_fetch_is_kept(self, db, monkeypatch):
        """Another writer quarantined the order with its payload while ML was being asked: the not_found answer
        must not delete that write error."""
        _miss(db, 507)

        async def _meanwhile(order_id):
            db.query(MlOrdersOpsCuarentena).filter_by(order_id=order_id).update(
                {"raw_order": {"id": order_id}, "error": ingestion_service.PERMANENT_TAG + "boom"},
                synchronize_session=False,
            )
            db.commit()
            return OrderFetch("not_found")

        monkeypatch.setattr(ml_webhook_client, "fetch_order", _meanwhile)

        assert service.refetch_unresolved_orders().attempted == 0

        row = _row(db, 507)
        assert row.raw_order == {"id": 507}
        assert row.error == ingestion_service.PERMANENT_TAG + "boom"

    def test_an_order_ml_gives_back_is_not_written_over_a_payload_that_arrived_meanwhile(self, db, monkeypatch):
        """The row now holds a write error with its own payload: the replay owns it, the re-fetch leaves it."""
        _miss(db, 510)

        async def _meanwhile(order_id):
            db.query(MlOrdersOpsCuarentena).filter_by(order_id=order_id).update(
                {"raw_order": {"id": order_id}, "error": ingestion_service.PERMANENT_TAG + "boom"},
                synchronize_session=False,
            )
            db.commit()
            return OrderFetch("ok", _order(order_id))

        monkeypatch.setattr(ml_webhook_client, "fetch_order", _meanwhile)

        result = service.refetch_unresolved_orders()

        assert (result.attempted, result.landed, result.failed) == (0, 0, 0)
        assert _row(db, 510).raw_order == {"id": 510}
        assert db.query(MlOrdersOps).filter_by(order_id=510).count() == 0

    def test_the_pass_is_bounded_by_its_limit(self, db, monkeypatch):
        for order_id in (511, 512, 513):
            _miss(db, order_id)
        _ml_answers(monkeypatch, {i: OrderFetch("error") for i in (511, 512, 513)})

        assert service.refetch_unresolved_orders(limit=2).attempted == 2

    def test_no_new_fetch_starts_past_the_deadline(self, db, monkeypatch):
        _miss(db, 521)
        mock = _ml_answers(monkeypatch, {})

        result = service.refetch_unresolved_orders(deadline=datetime.now(timezone.utc) - timedelta(seconds=1))

        assert result.attempted == 0
        mock.assert_not_called()
        assert _row(db, 521).intentos == 1

    def test_flag_off_is_a_no_op(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        _miss(db, 531)
        mock = _ml_answers(monkeypatch, {})

        assert service.refetch_unresolved_orders().attempted == 0
        mock.assert_not_called()
