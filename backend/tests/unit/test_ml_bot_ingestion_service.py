"""
T-C1..T-C5: Unit tests — services/ml_questions/ingestion_service.py (Slice C)

Covers (spec R-101/R-102/R-103, design §4, ADR-1/ADR-5/ADR-7):
- Cross-DB read of mlwebhook `webhooks` (topic='questions') via a swappable
  fetch function, filtered by the `ingest_cursor_ts` scalar cursor.
- Idempotent upsert into `ml_bot_questions` keyed by `ml_question_id` — no
  duplicates on re-poll.
- Only `UNANSWERED` questions are persisted; answered-elsewhere questions
  are skipped.
- Cursor advances atomically to the max `received_at` seen in the batch.
- mlwebhook unreachable -> logs + returns without raising (no crash of the
  background task loop).
- Session discipline (ADR-5): no pricing-app DB session is held open across
  the cross-DB read or the ML API call — each write is a short
  `get_background_db()` block.
- Datetimes passed into `policy` functions from this path MUST be
  timezone-aware (integration gotcha — policy treats naive as local wall-clock).

No pytest-asyncio in this project (see tests/unit/test_sync_stock_por_deposito.py)
— async code is driven with `asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import QuestionNotFoundError
from app.services.ml_questions import ingestion_service


class _ctx:
    """Minimal context-manager stub so `get_background_db()` returns the
    test's transactional `db` fixture session instead of opening a new
    SQLAlchemy engine connection.

    Uses a SAVEPOINT (`begin_nested`) per call so a rollback (e.g. on
    IntegrityError, mirroring production's short-lived independent session)
    only undoes that one block's writes — not the whole test's setup, which
    shares the same outer `db` session/transaction across multiple
    `get_background_db()` calls within a single test."""

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
    db.add(MlBotConfig(clave="ingest_cursor_ts", valor=value, tipo="string"))
    db.flush()


def _webhook_row(resource: str, received_at: datetime) -> dict:
    return {
        "resource": resource,
        "topic": "questions",
        "webhook_id": 111,
        "received_at": received_at,
    }


def _ml_question(question_id: int, *, status: str = "UNANSWERED", item_id: str = "MLA123") -> dict:
    return {
        "id": question_id,
        "text": "¿Tienen stock?",
        "status": status,
        "item_id": item_id,
        "date_created": "2026-07-06T22:00:00.000-03:00",
        "from": {"id": 999, "nickname": "comprador1"},
    }


class TestExtractQuestionId:
    def test_extracts_trailing_id(self) -> None:
        assert ingestion_service._extract_question_id("/questions/123456789") == 123456789

    def test_returns_none_for_malformed_resource(self) -> None:
        assert ingestion_service._extract_question_id("/items/MLA123") is None
        assert ingestion_service._extract_question_id("") is None


class TestIngestNewQuestions:
    def test_ingests_new_unanswered_question(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/555", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(555)),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 1
        row = db.query(MlBotQuestion).filter_by(ml_question_id=555).one()
        assert row.status == "received"
        assert row.item_id == "MLA123"
        assert row.buyer_nickname == "comprador1"

    def test_skips_answered_elsewhere(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/556", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(556, status="ANSWERED")),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        assert stats["skipped_answered"] == 1
        assert db.query(MlBotQuestion).filter_by(ml_question_id=556).first() is None

    def test_idempotent_on_duplicate_ml_question_id(self, db) -> None:
        _seed_cursor(db)
        db.add(
            MlBotQuestion(
                ml_question_id=557,
                item_id="MLA123",
                question_text="ya existe",
                question_date=datetime(2026, 7, 6, 20, 0, tzinfo=timezone.utc),
                status="received",
            )
        )
        db.flush()
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/557", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(557)),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        assert stats["duplicates"] == 1
        assert db.query(MlBotQuestion).filter_by(ml_question_id=557).count() == 1

    def test_advances_cursor_to_max_received_at(self, db) -> None:
        _seed_cursor(db)
        earlier = datetime(2026, 7, 6, 21, 0, tzinfo=timezone.utc)
        later = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[
                    _webhook_row("/questions/558", earlier),
                    _webhook_row("/questions/559", later),
                ],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(side_effect=[_ml_question(558), _ml_question(559)]),
            ),
        ):
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == later.isoformat()

    def test_get_question_failure_does_not_advance_cursor(self, db) -> None:
        """CRITICAL regression guard: `ml_client.get_question()` returns None
        for both a permanent 404 and a transient error (it can't tell them
        apart) — the cursor must NOT advance past a row whose fetch failed,
        or that buyer question is silently lost forever (never retried)."""
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/560", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        assert stats["error"] is True
        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == ""  # cursor NOT advanced

    def test_mlwebhook_unreachable_logs_and_returns(self, db, caplog) -> None:
        _seed_cursor(db)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        assert stats["error"] is True

    def test_does_not_call_eligibility_check(self, db) -> None:
        """WARNING fix: `run_ml_questions_ingest_cycle` never called `policy`
        for anything meaningful — this slice never drafts, so the dead
        `is_eligible_for_bot` call (result discarded) is removed entirely."""
        _seed_cursor(db)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(ingestion_service, "fetch_new_webhook_rows", return_value=[]),
            patch(
                "app.services.ml_questions.ingestion_service.policy.is_eligible_for_bot",
            ) as mock_eligible,
        ):
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        mock_eligible.assert_not_called()

    def test_404_skips_row_and_advances_cursor(self, db) -> None:
        """CRITICAL fix: a deleted question (404) must not stall ingestion —
        it's a terminal outcome, the row is skipped and the cursor advances
        past it, logging loudly."""
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/561", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(side_effect=QuestionNotFoundError(561)),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == received.isoformat()
        assert db.query(MlBotQuestion).filter_by(ml_question_id=561).first() is None

    def test_404_then_subsequent_row_ingests_same_tick(self, db) -> None:
        """A 404'd row must not block subsequent, newer rows in the same tick."""
        _seed_cursor(db)
        earlier = datetime(2026, 7, 6, 21, 0, tzinfo=timezone.utc)
        later = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[
                    _webhook_row("/questions/562", earlier),
                    _webhook_row("/questions/563", later),
                ],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(side_effect=[QuestionNotFoundError(562), _ml_question(563)]),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 1
        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == later.isoformat()
        assert db.query(MlBotQuestion).filter_by(ml_question_id=563).one().status == "received"

    def test_stuck_row_gives_up_after_max_attempts(self, db) -> None:
        """A permanently-transient failure (e.g. expired token) at the same
        cursor position must not stall ingestion forever — after
        `_MAX_STUCK_ATTEMPTS` ticks it's skipped with a loud give-up log."""
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/564", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            for tick in range(1, ingestion_service._MAX_STUCK_ATTEMPTS + 1):
                stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == received.isoformat()
        assert stats["ingested"] == 0
        assert db.query(MlBotQuestion).filter_by(ml_question_id=564).first() is None

        attempts_row = db.query(MlBotConfig).filter_by(clave="ingest_stuck_attempts").one()
        assert attempts_row.valor == "0"

    def test_stuck_counter_resets_when_cursor_advances_normally(self, db) -> None:
        """A stuck counter accumulated at one cursor position must not carry
        over once a tick successfully advances the cursor."""
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/565", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        attempts_row = db.query(MlBotConfig).filter_by(clave="ingest_stuck_attempts").one()
        assert attempts_row.valor == "2"

        later = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc)
        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/565", later)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(565)),
            ),
        ):
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        attempts_row = db.query(MlBotConfig).filter_by(clave="ingest_stuck_attempts").one()
        assert attempts_row.valor == "0"


class TestParseQuestionDate:
    def test_naive_iso_input_stored_as_aware_utc(self) -> None:
        parsed = ingestion_service._parse_question_date("2026-07-06T22:00:00")
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0
