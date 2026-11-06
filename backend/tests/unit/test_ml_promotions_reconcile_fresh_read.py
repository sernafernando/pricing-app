"""Ambiguous promo writes (timeout/5xx) are reconciled against a FRESH live read, not the mirror alone.

`ml_item_promotions` is fed by webhooks and can lag behind ML. After an ambiguous enroll or remove, a mirror that
does not show the write in effect (or shows a row with no usable status) is not proof either way: the live item read
(`ml_webhook_client.get_item_promotions`) decides, and when that read cannot confirm the outcome either the result is
`ambiguous`, never `reconciled_not_applied`. Every reconciled outcome queues the item refresh
(`promo_refresh_pending`) so the mirror catches up, and only an applied one leaves an `ml_write_log` row.

Proxy and live payloads use the same shapes as `test_ml_write_log_promotions.py`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.models.ml_write_log import MlWriteLog
from app.models.promo_refresh_pending import PromoRefreshPending
from app.models.usuario import Usuario
from app.services import ml_promotions_write_service as write_service

MLA = "MLA123456789"

_LIVE_DEAL_CANDIDATE = [
    {
        "id": "DEAL-1",
        "type": "DEAL",
        "status": "candidate",
        "min_discounted_price": 850.0,
        "max_discounted_price": 950.0,
        "suggested_discounted_price": 900.0,
    }
]
_LIVE_DEAL_STARTED = [{**_LIVE_DEAL_CANDIDATE[0], "status": "started"}]

_OK_201 = {"ok": True, "status_code": 201, "ambiguous": False, "body": {"status": "candidate"}}
_OK_200 = {"ok": True, "status_code": 200, "ambiguous": False, "body": {"ok": True}}
_REJECTED_400 = {"ok": False, "status_code": 400, "ambiguous": False, "body": {"error": "bad"}}
_AMBIGUOUS_504 = {"ok": False, "status_code": 504, "ambiguous": True, "body": None}


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)
    monkeypatch.setattr(write_service, "_maybe_recompute_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_clear_hay_mejores_after_enroll", lambda *a, **k: None)


@pytest.fixture()
def bg_db(db, monkeypatch: pytest.MonkeyPatch):
    """Routes `get_background_db()` to the test session with the real exit contract (commit, or rollback +
    re-raise), so `ml_write_log` and `promo_refresh_pending` are written for real."""

    @contextmanager
    def _fake() -> Iterator:
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
    user = Usuario(username="promo_reconciler", email="promo_reconciler@example.com", nombre="Promo Reconciler")
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def immediate_refresh() -> Iterator[MagicMock]:
    """The immediate point-refresh and the Publicaciones ML queue are network/other-table side effects; the durable
    `promo_refresh_pending` retry is the one asserted against the database."""
    with (
        patch.object(write_service.ml_webhook_client, "refresh_item_promotions", return_value=None) as refresh,
        patch.object(write_service, "_enqueue_publications_refresh"),
    ):
        yield refresh


def _log_rows(db) -> list[MlWriteLog]:
    return db.query(MlWriteLog).order_by(MlWriteLog.id).all()


def _refresh_queued(db) -> bool:
    return db.query(PromoRefreshPending).filter(PromoRefreshPending.mla == MLA).count() == 1


class TestAmbiguousEnrollUsesFreshRead:
    def test_stale_mirror_but_live_shows_enrolled_is_applied(self, bg_db, usuario, immediate_refresh) -> None:
        """The mirror has not caught up (no row); the fresh live read shows the item enrolled."""
        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                side_effect=[_LIVE_DEAL_CANDIDATE, _LIVE_DEAL_STARTED],
            ) as live,
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_AMBIGUOUS_504) as enroll,
            patch.object(write_service, "fetch_item_promotions", return_value=[]),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        enroll.assert_called_once()  # never a retry of the write
        assert live.call_count == 2  # pre-write read + fresh reconciliation read
        assert outcome["status"] == "reconciled_applied"
        (row,) = _log_rows(bg_db)
        assert (row.action, row.target_id, row.payload["outcome"]) == ("enroll", "DEAL-1", "reconciled_applied")
        assert _refresh_queued(bg_db)

    def test_fresh_read_unavailable_is_ambiguous_not_not_applied(self, bg_db, usuario, immediate_refresh) -> None:
        mirror_row = {"mla": MLA, "promotion_id": "DEAL-1", "promotion_type": "DEAL", "status": "candidate"}
        with (
            patch.object(
                write_service.ml_webhook_client, "get_item_promotions", side_effect=[_LIVE_DEAL_CANDIDATE, None]
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service, "fetch_item_promotions", return_value=[mirror_row]),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "ambiguous"
        assert outcome["detail"]
        assert _log_rows(bg_db) == []
        assert _refresh_queued(bg_db)

    def test_fresh_read_confirms_not_enrolled_is_not_applied_and_queues_refresh(
        self, bg_db, usuario, immediate_refresh
    ) -> None:
        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                side_effect=[_LIVE_DEAL_CANDIDATE, _LIVE_DEAL_CANDIDATE],
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service, "fetch_item_promotions", return_value=[]),
        ):
            outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)

        assert outcome["status"] == "reconciled_not_applied"
        assert _log_rows(bg_db) == []
        assert _refresh_queued(bg_db)


class TestAmbiguousRemoveFailsClosed:
    @pytest.mark.parametrize(
        "mirror_rows",
        [
            [{"mla": MLA, "promotion_id": "DEAL-1", "promotion_type": "DEAL", "status": None}],
            [{"mla": MLA, "promotion_id": "DEAL-1", "promotion_type": "DEAL", "status": "paused_by_ml"}],
        ],
        ids=["status-none", "status-unknown"],
    )
    def test_unknown_mirror_status_and_no_fresh_read_is_ambiguous(
        self, bg_db, usuario, immediate_refresh, mirror_rows
    ) -> None:
        """A row with no usable status is no proof the DELETE worked, exactly like an enroll."""
        with (
            patch.object(write_service.ml_webhook_client, "remove_item", return_value=_AMBIGUOUS_504) as remove,
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=None),
            patch.object(write_service, "fetch_item_promotions", return_value=mirror_rows),
        ):
            outcome = write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        remove.assert_called_once()
        assert outcome["status"] == "ambiguous"
        assert _log_rows(bg_db) == []
        assert _refresh_queued(bg_db)

    def test_unknown_mirror_status_and_live_still_enrolled_is_not_applied(
        self, bg_db, usuario, immediate_refresh
    ) -> None:
        mirror_row = {"mla": MLA, "promotion_id": "DEAL-1", "promotion_type": "DEAL", "status": None}
        with (
            patch.object(write_service.ml_webhook_client, "remove_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_LIVE_DEAL_STARTED),
            patch.object(write_service, "fetch_item_promotions", return_value=[mirror_row]),
        ):
            outcome = write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        assert outcome["status"] == "reconciled_not_applied"
        assert _log_rows(bg_db) == []
        assert _refresh_queued(bg_db)

    def test_no_mirror_row_and_live_back_to_candidate_is_applied(self, bg_db, usuario, immediate_refresh) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "remove_item", return_value=_AMBIGUOUS_504),
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_LIVE_DEAL_CANDIDATE),
            patch.object(write_service, "fetch_item_promotions", return_value=[]),
        ):
            outcome = write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        assert outcome["status"] == "reconciled_applied"
        (row,) = _log_rows(bg_db)
        assert (row.action, row.payload["outcome"]) == ("remove", "reconciled_applied")
        assert _refresh_queued(bg_db)


class TestClearAnswersUnchanged:
    """A clear 2xx/4xx never reconciles: no mirror read, no extra live read, same outcome as before."""

    @pytest.mark.parametrize(
        ("operation", "proxy", "expected", "logged", "refreshed"),
        [
            ("enroll", _OK_201, "submitted", True, True),
            ("enroll", _REJECTED_400, "rejected_by_proxy", False, False),
            ("remove", _OK_200, "submitted", True, True),
            ("remove", _REJECTED_400, "rejected_by_proxy", False, False),
        ],
    )
    def test_clear_answer(
        self, bg_db, usuario, immediate_refresh, operation, proxy, expected, logged, refreshed
    ) -> None:
        with (
            patch.object(
                write_service.ml_webhook_client, "get_item_promotions", return_value=_LIVE_DEAL_CANDIDATE
            ) as live,
            patch.object(write_service.ml_webhook_client, "enroll_item", return_value=proxy),
            patch.object(write_service.ml_webhook_client, "remove_item", return_value=proxy),
            patch.object(write_service, "fetch_item_promotions") as mirror,
        ):
            if operation == "enroll":
                outcome = write_service.enroll_one_item(MLA, "DEAL-1", "DEAL", deal_price=900.0, usuario_id=usuario.id)
            else:
                outcome = write_service.remove_one_item(MLA, "DEAL", "DEAL-1", usuario_id=usuario.id)

        assert outcome["status"] == expected
        mirror.assert_not_called()
        assert live.call_count == (1 if operation == "enroll" else 0)
        assert len(_log_rows(bg_db)) == (1 if logged else 0)
        assert _refresh_queued(bg_db) is refreshed
