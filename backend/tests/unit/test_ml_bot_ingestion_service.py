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
        assert cursor_row.valor == f"{later.isoformat()}|111"  # composite cursor (WARNING fix)

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
        assert cursor_row.valor == f"{received.isoformat()}|111"
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
        assert cursor_row.valor == f"{later.isoformat()}|111"
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
        assert cursor_row.valor == f"{received.isoformat()}|111"
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

    def test_stuck_row_giveup_breaks_tick_leaves_later_rows_untouched(self, db) -> None:
        """CRITICAL fix: the stuck/attempts machinery applies ONLY to the
        first row of the tick (the persisted-cursor position). Once that row
        gives up, the tick BREAKS — a later row in the SAME batch must not be
        touched this tick, and must ingest normally next tick (fresh attempts
        counter), instead of being silently given up on its first attempt."""
        _seed_cursor(db)
        stuck_received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)
        fresh_received = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc)

        # Ticks 1..9: only the stuck row is fetched (simulates it being the
        # sole unprocessed row until it finally gives up on tick 10).
        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/570", stuck_received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            for _ in range(ingestion_service._MAX_STUCK_ATTEMPTS - 1):
                asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        # Tick 10: the stuck row (index 0) AND a fresh newer row (index 1)
        # are both in the batch. The stuck row gives up and the tick must
        # BREAK — the fresh row is not touched this tick at all.
        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[
                    _webhook_row("/questions/570", stuck_received),
                    _webhook_row("/questions/571", fresh_received),
                ],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(side_effect=AssertionError("fresh row must not be fetched this tick")),
            ) as mock_get,
        ):
            mock_get.side_effect = None
            mock_get.return_value = None  # only ever called for the stuck row
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert mock_get.await_count == 1  # only the stuck row was attempted
        assert db.query(MlBotQuestion).filter_by(ml_question_id=571).first() is None
        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert stuck_received.isoformat() in cursor_row.valor  # cursor advanced past give-up row

        # Next tick: only the fresh row remains (cursor moved past the
        # stuck one) and must ingest normally with a fresh attempts cycle.
        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/571", fresh_received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(571)),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 1
        assert db.query(MlBotQuestion).filter_by(ml_question_id=571).one().status == "received"

    def test_fresh_row_after_giveup_gets_own_attempts_cycle(self, db) -> None:
        """A row that starts failing transiently right after a DIFFERENT
        row's give-up must NOT be given up on its first attempt — it gets
        its own full `_MAX_STUCK_ATTEMPTS` cycle across subsequent ticks."""
        _seed_cursor(db)
        stuck_received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)
        fresh_received = datetime(2026, 7, 6, 23, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/572", stuck_received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            for _ in range(ingestion_service._MAX_STUCK_ATTEMPTS):
                asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        # Now the fresh row is the only one left, and it also fails
        # transiently — this must be attempt 1 for it, not an instant give-up.
        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/573", fresh_received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=None),
            ),
        ):
            stats = asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        assert stats["ingested"] == 0
        attempts_row = db.query(MlBotConfig).filter_by(clave="ingest_stuck_attempts").one()
        assert attempts_row.valor == "1"  # fresh cycle, not given up immediately
        assert db.query(MlBotQuestion).filter_by(ml_question_id=573).first() is None


class TestCompositeCursor:
    """WARNING fix: strict `>` cursor + LIMIT with no tie-breaker can strand
    same-timestamp rows at the batch boundary. Adds `webhook_id` as a
    secondary sort/filter key and persists a composite "ISO_TS|webhook_id"
    cursor, with backward-compat parsing of the old scalar format."""

    def test_parse_cursor_old_scalar_format_backward_compat(self) -> None:
        ts, wid = ingestion_service._parse_cursor("2026-07-06T22:00:00+00:00")
        assert ts == "2026-07-06T22:00:00+00:00"
        assert wid == 0

    def test_parse_cursor_composite_format(self) -> None:
        ts, wid = ingestion_service._parse_cursor("2026-07-06T22:00:00+00:00|555")
        assert ts == "2026-07-06T22:00:00+00:00"
        assert wid == 555

    def test_parse_cursor_empty_or_none(self) -> None:
        assert ingestion_service._parse_cursor(None) == (None, 0)
        assert ingestion_service._parse_cursor("") == (None, 0)

    def test_format_cursor_round_trip(self) -> None:
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)
        formatted = ingestion_service._format_cursor(received, 42)
        assert formatted == f"{received.isoformat()}|42"
        ts, wid = ingestion_service._parse_cursor(formatted)
        assert ts == received.isoformat()
        assert wid == 42

    def test_fetch_query_uses_webhook_id_tiebreaker(self) -> None:
        mock_conn = AsyncMock() if False else None
        with patch("app.services.ml_questions.ingestion_service.get_mlwebhook_engine") as mock_engine_fn:
            from unittest.mock import MagicMock

            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            mock_conn = mock_engine.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []

            ingestion_service.fetch_new_webhook_rows(since="2026-07-06T22:00:00+00:00|111", limit=50)

            _, kwargs_or_params = mock_conn.execute.call_args
            sql_text = str(mock_conn.execute.call_args[0][0])
            params = mock_conn.execute.call_args[0][1]

        assert "webhook_id > :since_id" in sql_text
        assert "ORDER BY received_at ASC, webhook_id ASC" in sql_text
        assert params["since_ts"] == "2026-07-06T22:00:00+00:00"
        assert params["since_id"] == 111

    def test_fetch_query_old_format_cursor_defaults_since_id_zero(self) -> None:
        with patch("app.services.ml_questions.ingestion_service.get_mlwebhook_engine") as mock_engine_fn:
            from unittest.mock import MagicMock

            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            mock_conn = mock_engine.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []

            ingestion_service.fetch_new_webhook_rows(since="2026-07-06T22:00:00+00:00", limit=50)

            params = mock_conn.execute.call_args[0][1]

        assert params["since_ts"] == "2026-07-06T22:00:00+00:00"
        assert params["since_id"] == 0

    def test_cursor_persisted_in_composite_format_after_ingest(self, db) -> None:
        _seed_cursor(db)
        received = datetime(2026, 7, 6, 22, 0, tzinfo=timezone.utc)

        with (
            patch("app.services.ml_questions.ingestion_service.get_background_db", return_value=_ctx(db)),
            patch.object(
                ingestion_service,
                "fetch_new_webhook_rows",
                return_value=[_webhook_row("/questions/580", received)],
            ),
            patch.object(
                ingestion_service.ml_client,
                "get_question",
                new=AsyncMock(return_value=_ml_question(580)),
            ),
        ):
            asyncio.run(ingestion_service.run_ml_questions_ingest_cycle())

        cursor_row = db.query(MlBotConfig).filter_by(clave="ingest_cursor_ts").one()
        assert cursor_row.valor == f"{received.isoformat()}|111"  # webhook_id from _webhook_row


class TestParseQuestionDate:
    def test_naive_iso_input_stored_as_aware_utc(self) -> None:
        parsed = ingestion_service._parse_question_date("2026-07-06T22:00:00")
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0
