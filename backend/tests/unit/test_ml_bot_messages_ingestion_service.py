"""
PR1 — unit tests for services/ml_messages/ingestion_service.py (ML bot
postventa messages MVP, read-only).

Mirrors tests/unit/test_ml_bot_ingestion_service.py's `_ctx` stub + fixture
conventions (ADR-5 short-lived session discipline, ADR-7 cursor CAS).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_message import MlBotMessage
from app.services.ml_api_client import MessageNotFoundError
from app.services.ml_messages import ingestion_service


class _ctx:
    """Mirrors `test_ml_bot_ingestion_service.py`'s `_ctx` stub — makes
    `get_background_db()` return the test's transactional `db` fixture
    session via a SAVEPOINT per call."""

    def __init__(self, db) -> None:
        self._db = db
        self._nested = None

    def __enter__(self):
        self._nested = self._db.begin_nested()
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._nested.commit()
        else:
            self._nested.rollback()
        return False


def _seed_cursor(db, value: str = "") -> None:
    db.add(MlBotConfig(clave="ingest_cursor_ts_messages", valor=value, tipo="string"))
    db.flush()


def _webhook_row(resource: str, actions: list, received_at: datetime, webhook_id: object = "wh-msg-1") -> dict:
    return {
        "resource": resource,
        "actions": actions,
        "topic": "messages",
        "webhook_id": webhook_id,
        "received_at": received_at,
    }


def _ml_message(
    message_id: str,
    *,
    from_user_id: int = 999,
    nickname: str = "comprador1",
    status: str = "available",
    pack_id: str = "PACK123",
    moderation_status=None,
    text: str = "hola, tengo una duda",
) -> dict:
    message_resources = [{"name": "packs", "id": pack_id}] if pack_id else []
    payload = {
        "id": message_id,
        "text": text,
        "status": status,
        "date_created": "2026-07-10T12:00:00.000-03:00",
        "from": {"user_id": from_user_id, "nickname": nickname},
        "message_resources": message_resources,
    }
    if moderation_status is not None:
        payload["message_moderation"] = {"status": moderation_status}
    return payload


def _patch(db, webhook_rows, get_message_result):
    return (
        patch("app.services.ml_messages.ingestion_service.get_background_db", return_value=_ctx(db)),
        patch.object(ingestion_service, "fetch_new_webhook_rows", return_value=webhook_rows),
        patch.object(ingestion_service.ml_client, "get_message", new=AsyncMock(return_value=get_message_result)),
    )


class TestCreatedAction:
    def test_created_action_filter_outgoing_seller_id_never_persisted(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = _ml_message("msg-out-1", from_user_id=413658225)

        p1, p2, p3 = _patch(db, [_webhook_row("msg-out-1", ["created"], received)], payload)
        with p1, p2, p3:
            with patch.object(ingestion_service, "sse_publish", new=AsyncMock()) as sse:
                stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["outgoing_skipped"] == 1
        assert db.query(MlBotMessage).count() == 0
        sse.assert_not_called()

    def test_created_action_idempotent_on_duplicate_ml_message_id(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = _ml_message("msg-dup-1")

        p1, p2, p3 = _patch(db, [_webhook_row("msg-dup-1", ["created"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        # Second tick, cursor unchanged (simulate re-delivery at same cursor).
        db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").update({"valor": ""})
        db.flush()

        p1, p2, p3 = _patch(db, [_webhook_row("msg-dup-1", ["created"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["duplicates"] == 1
        assert db.query(MlBotMessage).filter_by(ml_message_id="msg-dup-1").count() == 1

    def test_created_action_message_deleted_in_ml_skipped_no_crash(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_messages.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("msg-gone", ["created"], received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_message",
                new=AsyncMock(side_effect=MessageNotFoundError("msg-gone")),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["created"] == 0
        assert db.query(MlBotMessage).count() == 0
        cursor = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").one()
        assert cursor.valor != ""

    def test_pack_id_absent_from_message_resources_persists_with_null_pack(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = _ml_message("msg-nopack", pack_id=None)

        p1, p2, p3 = _patch(db, [_webhook_row("msg-nopack", ["created"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["created"] == 1
        row = db.query(MlBotMessage).filter_by(ml_message_id="msg-nopack").one()
        assert row.pack_id is None

    def test_moderation_status_persisted_regardless_of_value(self, db) -> None:
        _seed_cursor(db)
        for idx, moderation_status in enumerate(["clean", "pending", None, "blocked"]):
            message_id = f"msg-mod-{idx}"
            received = datetime(2026, 7, 10, 12, idx, tzinfo=timezone.utc)
            payload = _ml_message(message_id, moderation_status=moderation_status)

            p1, p2, p3 = _patch(db, [_webhook_row(message_id, ["created"], received, webhook_id=f"wh-{idx}")], payload)
            with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
                asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

            # Reset cursor between iterations so each message is treated as new.
            db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").update({"valor": ""})
            db.flush()

            row = db.query(MlBotMessage).filter_by(ml_message_id=message_id).one()
            assert row.moderation_status == moderation_status

    def test_sse_publish_message_created_fires_after_insert(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = _ml_message("msg-sse-1")

        p1, p2, p3 = _patch(db, [_webhook_row("msg-sse-1", ["created"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()) as sse:
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["created"] == 1
        sse.assert_awaited_once_with("ml_bot:messages", {"type": "message_created", "id": "msg-sse-1"})


class TestReadAction:
    def test_read_action_updates_read_at_when_row_exists(self, db) -> None:
        received_created = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        db.add(
            MlBotMessage(
                ml_message_id="msg-read-1",
                seller_id=413658225,
                text="hola",
                status="available",
                received_at=received_created,
            )
        )
        db.flush()
        _seed_cursor(db)

        received_read = datetime(2026, 7, 10, 12, 5, tzinfo=timezone.utc)
        payload = {"id": "msg-read-1", "date_read": "2026-07-10T12:05:00.000-03:00"}

        p1, p2, p3 = _patch(db, [_webhook_row("msg-read-1", ["read"], received_read)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["read_updated"] == 1
        row = db.query(MlBotMessage).filter_by(ml_message_id="msg-read-1").one()
        assert row.read_at is not None

    def test_read_action_log_and_skip_when_row_missing(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = {"id": "msg-missing", "date_read": "2026-07-10T12:00:00.000-03:00"}

        p1, p2, p3 = _patch(db, [_webhook_row("msg-missing", ["read"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()) as sse:
            stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["read_skipped"] == 1
        assert db.query(MlBotMessage).count() == 0
        sse.assert_not_called()


class TestCursorCAS:
    def test_cursor_cas_reread_skips_write_on_manual_mid_tick_edit(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        payload = _ml_message("msg-cas-1")

        def fake_get_message(*args, **kwargs):
            # Simulate a manual admin edit of the cursor happening mid-tick.
            db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").update({"valor": "manual-override"})
            db.flush()
            return payload

        with (
            patch("app.services.ml_messages.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("msg-cas-1", ["created"], received)],
            ),
            patch.object(ingestion_service.ml_client, "get_message", new=AsyncMock(side_effect=fake_get_message)),
            patch.object(ingestion_service, "sse_publish", new=AsyncMock()),
        ):
            asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        cursor = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").one()
        assert cursor.valor == "manual-override"

    def test_stuck_row_bounded_retry_after_max_attempts(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        for _ in range(10):
            with (
                patch("app.services.ml_messages.ingestion_service.get_background_db", return_value=_ctx(db)),
                patch.object(
                    ingestion_service,
                    "fetch_new_webhook_rows",
                    return_value=[_webhook_row("msg-stuck-1", ["created"], received)],
                ),
                patch.object(ingestion_service.ml_client, "get_message", new=AsyncMock(return_value=None)),
            ):
                stats = asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())

        assert stats["error"] is True
        cursor = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").one()
        assert cursor.valor != ""
