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
    text_as_dict: bool = False,
    wrapped: bool = False,
    received: str = "2026-07-10T12:00:00.000-03:00",
    read: str | None = None,
) -> dict:
    """Mirrors ML's REAL post-sale message shape (verified against the working
    `routers/seriales_messages.py` parser): dates in a `message_date` object,
    `text` optionally a `{"plain": ...}` dict, attachments in
    `message_attachments`, and the whole thing optionally wrapped in
    `{"messages": [...]}`."""
    message_resources = [{"name": "packs", "id": pack_id}] if pack_id else []
    message_date: dict = {"received": received, "created": received}
    if read is not None:
        message_date["read"] = read
    payload = {
        "id": message_id,
        "text": {"plain": text} if text_as_dict else text,
        "status": status,
        "message_date": message_date,
        "from": {"user_id": from_user_id, "nickname": nickname},
        "message_resources": message_resources,
    }
    if moderation_status is not None:
        payload["message_moderation"] = {"status": moderation_status}
    if wrapped:
        return {"messages": [payload], "paging": {"total": 1}}
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


class TestFetcherSchemaAssumption:
    """Regression guards for the mlwebhook `webhooks` table shape — `actions`
    is NOT a top-level column, it lives inside the `payload` JSONB. Mocked-
    fetcher unit tests silently pass a wrong SQL through; this suite asserts
    the SQL string built by `fetch_new_webhook_rows` extracts from payload."""

    def test_sql_extracts_actions_from_payload_jsonb(self) -> None:
        import re

        captured: dict[str, str] = {}

        class _FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, stmt, params):
                captured["sql"] = str(stmt)

                class _R:
                    def fetchall(self_inner):
                        return []

                return _R()

        class _FakeEngine:
            def connect(self):
                return _FakeConn()

        with patch(
            "app.services.ml_messages.ingestion_service.get_mlwebhook_engine",
            return_value=_FakeEngine(),
        ):
            ingestion_service.fetch_new_webhook_rows(since=None, limit=10)

        sql = captured["sql"]
        assert re.search(r"payload\s*->\s*'actions'", sql), (
            f"SQL must extract actions from payload JSONB (webhooks has no actions column); got: {sql!r}"
        )


class TestRealMlShapeRegression:
    """Regression for the empty-message bug: the ingestion previously read the
    wrong ML keys (flat `text`/`date_created`, no unwrap, no text-dict), so rows
    persisted with empty text, empty buyer, and a fallback `received_at`. These
    tests ASSERT the actual persisted field values against ML's real shape."""

    def _run_created(self, db, payload, msg_id="msg-real-1"):
        received = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        p1, p2, p3 = _patch(db, [_webhook_row(msg_id, ["created"], received)], payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())
        return db.query(MlBotMessage).filter_by(ml_message_id=msg_id).first()

    def test_created_populates_text_buyer_and_real_received_at(self, db) -> None:
        _seed_cursor(db)
        row = self._run_created(db, _ml_message("msg-real-1", text="viene con caja?"))
        assert row is not None
        assert row.text == "viene con caja?"  # not empty
        assert row.buyer_id == 999  # not None
        assert row.buyer_nickname == "comprador1"
        assert row.pack_id == "PACK123"
        # real message date (2026-07-10), NOT the now() ingestion-time fallback
        assert (row.received_at.year, row.received_at.month, row.received_at.day) == (2026, 7, 10)

    def test_created_extracts_plain_from_text_dict(self, db) -> None:
        _seed_cursor(db)
        row = self._run_created(db, _ml_message("msg-real-1", text="soy un dict", text_as_dict=True))
        assert row is not None
        assert row.text == "soy un dict"  # not the dict repr, not empty

    def test_created_unwraps_messages_wrapper(self, db) -> None:
        _seed_cursor(db)
        row = self._run_created(db, _ml_message("msg-real-1", text="envuelto", wrapped=True))
        assert row is not None
        assert row.text == "envuelto"  # unwrapped, not empty
        assert row.buyer_id == 999

    def test_read_sets_read_at_from_message_date(self, db) -> None:
        _seed_cursor(db)
        # create first
        self._run_created(db, _ml_message("msg-read-1", text="hola"), msg_id="msg-read-1")
        db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts_messages").update({"valor": ""})
        db.flush()
        # then a read event carrying message_date.read
        read_payload = _ml_message("msg-read-1", read="2026-07-11T09:30:00.000-03:00")
        received = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
        p1, p2, p3 = _patch(db, [_webhook_row("msg-read-1", ["read"], received)], read_payload)
        with p1, p2, p3, patch.object(ingestion_service, "sse_publish", new=AsyncMock()):
            asyncio.run(ingestion_service.run_ml_messages_ingest_cycle())
        row = db.query(MlBotMessage).filter_by(ml_message_id="msg-read-1").first()
        assert row.read_at is not None
        assert (row.read_at.year, row.read_at.month, row.read_at.day) == (2026, 7, 11)
