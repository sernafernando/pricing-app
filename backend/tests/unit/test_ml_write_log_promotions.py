"""`ml_write_log` rows for promotion enroll/remove (eventos-historial-legibles T2).

A row is written ONLY after ML confirmed the write (`submitted`, or an
ambiguous write that reconciliation shows applied). A rejected/ambiguous
write leaves nothing, and a failure to write the log never changes the
outcome of a write that already happened at ML.

The proxy/live payloads below are the same shapes the existing promotions
write-service tests use (`test_ml_promotions_write_service.py`).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.models.ml_write_log import MlWriteLog
from app.models.usuario import Usuario
from app.services import ml_promotions_write_service as write_service

MLA = "MLA123456789"


def _live_deal(promotion_id: str = "DEAL-1") -> list:
    return [
        {
            "id": promotion_id,
            "type": "DEAL",
            "min_discounted_price": 850.0,
            "max_discounted_price": 950.0,
            "suggested_discounted_price": 900.0,
        }
    ]


def _live_smart(status: str = "candidate", price: float = 1000.0, ref_id: str = "CANDIDATE-MLA123456789-1") -> list:
    return [{"id": "SMART-1", "type": "SMART", "status": status, "price": price, "ref_id": ref_id}]


_OK_201 = {"ok": True, "status_code": 201, "ambiguous": False, "body": {"status": "candidate"}}
_OK_200 = {"ok": True, "status_code": 200, "ambiguous": False, "body": {"ok": True}}
_REJECTED_400 = {"ok": False, "status_code": 400, "ambiguous": False, "body": {"error": "bad"}}
_AMBIGUOUS_504 = {"ok": False, "status_code": 504, "ambiguous": True, "body": None}


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)
    monkeypatch.setattr(write_service, "_maybe_refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_maybe_recompute_after_write", lambda *a, **k: None)


@pytest.fixture()
def bg_db(db, monkeypatch: pytest.MonkeyPatch):
    """Routes the service's short-lived `get_background_db()` to the test session,
    with the same exit contract as the real one: commit on a normal exit,
    rollback + re-raise on an exception. The `db` fixture's SAVEPOINT keeps the
    commit inside the test transaction."""

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
    user = Usuario(username="promo_writer", email="promo_writer@example.com", nombre="Promo Writer")
    db.add(user)
    db.flush()
    return user


def _rows(db) -> list[MlWriteLog]:
    return db.query(MlWriteLog).order_by(MlWriteLog.id).all()


class TestEnrollWritesLog:
    def test_enroll_success_writes_row_with_user(self, bg_db, usuario) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_OK_201),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "submitted"
        rows = _rows(bg_db)
        assert len(rows) == 1
        row = rows[0]
        assert (row.mla, row.resource, row.action) == (MLA, "promotion", "enroll")
        assert (row.target_id, row.promotion_type) == ("DEAL-1", "DEAL")
        assert row.usuario_id == usuario.id
        assert row.payload["deal_price"] == 900.0
        assert row.created_at is not None

    def test_smart_enroll_records_offer_and_confirmed_price(self, bg_db, usuario) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_smart()),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={
                    "ok": True,
                    "status_code": 201,
                    "ambiguous": False,
                    "body": {"offer_id": "OFFER-MLA123456789-1", "price": 1000.0},
                },
            ),
        ):
            write_service.enroll_one_item(MLA, "SMART-1", "SMART", precio_visto=1000.0, usuario_id=usuario.id)

        (row,) = _rows(bg_db)
        assert row.payload["offer_id"] == "OFFER-MLA123456789-1"
        assert row.payload["precio_visto"] == 1000.0
        assert row.payload["deal_price"] == 1000.0

    def test_system_write_has_null_user(self, bg_db) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_OK_201),
        ):
            write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0)

        (row,) = _rows(bg_db)
        assert row.usuario_id is None

    def test_proxy_rejection_writes_nothing(self, bg_db, usuario) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_REJECTED_400),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "rejected_by_proxy"
        assert _rows(bg_db) == []

    def test_local_rejection_writes_nothing(self, bg_db, usuario) -> None:
        with patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=10.0, usuario_id=usuario.id)

        assert outcome["status"] == "rejected_out_of_range"
        assert _rows(bg_db) == []

    def test_ambiguous_unresolved_writes_nothing(self, bg_db, usuario) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service, "fetch_item_promotions", side_effect=RuntimeError("db down")),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "ambiguous"
        assert _rows(bg_db) == []

    def test_ambiguous_reconciled_applied_writes_row(self, bg_db, usuario) -> None:
        mirror_row = {"mla": MLA, "promotion_id": "DEAL-1", "promotion_type": "DEAL", "status": "started"}
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service, "fetch_item_promotions", return_value=[mirror_row]),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "reconciled_applied"
        (row,) = _rows(bg_db)
        assert row.action == "enroll"
        assert row.payload["outcome"] == "reconciled_applied"

    def test_log_failure_never_changes_a_confirmed_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        @contextmanager
        def _broken():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(write_service, "get_background_db", _broken)
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_OK_201),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=7)

        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True


class TestRemoveWritesLog:
    def test_remove_success_writes_row(self, bg_db, usuario) -> None:
        with patch.object(write_service.ml_webhook_client, "remove_item", return_value=_OK_200):
            outcome = write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        assert outcome["status"] == "submitted"
        (row,) = _rows(bg_db)
        assert (row.action, row.target_id, row.promotion_type) == ("remove", "DEAL-1", "DEAL")
        assert row.usuario_id == usuario.id

    def test_remove_rejection_writes_nothing(self, bg_db, usuario) -> None:
        with patch.object(write_service.ml_webhook_client, "remove_item", return_value=_REJECTED_400):
            write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        assert _rows(bg_db) == []


class TestBulkWritesOneRowPerItem:
    """The bulk apply in the UI (PromoApplyControl) calls the per-item endpoint
    once per MLA; there is no backend bulk path that bypasses the service. Each
    item therefore leaves exactly one row."""

    def test_each_item_leaves_its_own_row(self, bg_db, usuario) -> None:
        mlas = ["MLA111", "MLA222", "MLA333"]
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live_deal()),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_OK_201),
        ):
            for mla in mlas:
                write_service.enroll_one_item(mla, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert [r.mla for r in _rows(bg_db)] == mlas
