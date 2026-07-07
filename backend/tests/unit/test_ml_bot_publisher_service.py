"""
T-E-1..T-E-N: Unit tests — services/ml_questions/publisher_service.py (Slice E)

Covers design §8 (wait-window publisher) + spec double-publish/idempotency
requirements:
- CAS claim (waiting -> publishing), skips rows claimed elsewhere.
- Only rows with wait_until <= now are picked up; future rows are untouched.
- Happy path -> `published`, published_at set, no DB session held during the
  ML POST (ADR-5).
- ML "already answered" 4xx -> treated as success-equivalent (`published`).
- Transient failure -> bounded retry (attempts read FRESH from DB) -> back to
  `waiting`; exhausted -> `failed` with `last_error`.
- Human takeover wins: a row in `taken_over` is never selected/published.
- Stale `publishing` claims (crash between claim and terminal write) are
  reclaimed back to `waiting` at the start of a cycle.

No pytest-asyncio in this project — async code is driven with `asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_questions import publisher_service


class _ctx:
    """Same SAVEPOINT-based stub used by the drafting/ingestion tests, so
    `get_background_db()` reuses the test's transactional `db` fixture."""

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


def _patch_db(db):
    return patch("app.services.ml_questions.publisher_service.get_background_db", return_value=_ctx(db))


_next_ml_question_id = iter(range(2000, 2_000_000))


def _seed_question(
    db,
    *,
    status: str = "waiting",
    wait_until: datetime | None = None,
    drafted_answer: str = "¡Hola! Sí, tenemos stock disponible.",
    attempts: int = 0,
    updated_at: datetime | None = None,
) -> MlBotQuestion:
    now = datetime.now(timezone.utc)
    row = MlBotQuestion(
        ml_question_id=next(_next_ml_question_id),
        item_id="MLA123",
        buyer_id=555,
        buyer_nickname="comprador1",
        question_text="¿Tienen stock del modelo azul?",
        question_date=now,
        status=status,
        drafted_answer=drafted_answer,
        answer_source="bot",
        wait_until=wait_until if wait_until is not None else now - timedelta(minutes=1),
        attempts=attempts,
    )
    db.add(row)
    db.flush()
    if updated_at is not None:
        db.execute(MlBotQuestion.__table__.update().where(MlBotQuestion.id == row.id).values(updated_at=updated_at))
        db.flush()
    return row


class TestDueSelection:
    def test_only_due_waiting_rows_are_published(self, db) -> None:
        due = _seed_question(db)
        future = _seed_question(db, wait_until=datetime.now(timezone.utc) + timedelta(minutes=10))
        db.commit()

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        db.refresh(due)
        db.refresh(future)
        assert due.status == "published"
        assert future.status == "waiting"

    def test_taken_over_row_is_never_published(self, db) -> None:
        row = _seed_question(db, status="taken_over")
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 0
        post_answer.assert_not_called()
        db.refresh(row)
        assert row.status == "taken_over"


class TestHappyPath:
    def test_publish_success_sets_published_at(self, db) -> None:
        row = _seed_question(db)
        db.commit()

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        db.refresh(row)
        assert row.status == "published"
        assert row.published_at is not None


class TestAlreadyAnswered:
    def test_already_answered_error_treated_as_success(self, db) -> None:
        from app.services.ml_api_client import QuestionAlreadyAnsweredError

        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(side_effect=QuestionAlreadyAnsweredError(row.ml_question_id))

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        db.refresh(row)
        assert row.status == "published"


class TestTransientFailure:
    def test_transient_failure_retries_then_stays_waiting(self, db) -> None:
        row = _seed_question(db, attempts=0)
        db.commit()
        post_answer = AsyncMock(return_value=None)

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["retry"] == 1
        db.refresh(row)
        assert row.status == "waiting"
        assert row.attempts == 1
        assert row.last_error is not None

    def test_exhausted_retries_marks_failed(self, db) -> None:
        row = _seed_question(db, attempts=publisher_service._MAX_ATTEMPTS - 1)
        db.commit()
        post_answer = AsyncMock(return_value=None)

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"
        assert row.attempts == publisher_service._MAX_ATTEMPTS


class TestStaleClaimReclaim:
    def test_stale_publishing_row_is_reclaimed_to_waiting(self, db) -> None:
        stale_threshold = datetime.now(timezone.utc) - timedelta(
            minutes=publisher_service._PUBLISHING_STALE_MINUTES + 5
        )
        row = _seed_question(db, status="publishing", updated_at=stale_threshold)
        db.commit()

        with _patch_db(db):
            reclaimed = publisher_service._reclaim_stale_publishing_claims(datetime.now(timezone.utc))

        assert reclaimed == 1
        db.refresh(row)
        assert row.status == "waiting"


class TestNoSessionAcrossPost:
    def test_post_answer_called_without_open_publisher_db_session(self, db) -> None:
        """ADR-5: the ML POST must not happen while a `get_background_db()`
        session from this module is open."""
        _seed_question(db)
        db.commit()

        session_open_during_call = {"value": None}
        real_get_background_db = publisher_service.get_background_db

        class _TrackingCtx(_ctx):
            def __enter__(self):
                session_open_during_call["value"] = "opened"
                return super().__enter__()

            def __exit__(self, exc_type, exc, tb):
                session_open_during_call["value"] = None
                return super().__exit__(exc_type, exc, tb)

        async def _fake_post_answer(*args, **kwargs):
            assert session_open_during_call["value"] is None, "DB session must be closed during ML POST"
            return {"id": 999}

        with (
            patch(
                "app.services.ml_questions.publisher_service.get_background_db",
                side_effect=lambda: _TrackingCtx(db),
            ),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(side_effect=_fake_post_answer),
            ),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        del real_get_background_db
