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

import pytest

from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import AnswerPostPermanentError
from app.services.ml_questions import publisher_service


@pytest.fixture(autouse=True)
def _default_auto_publish_enabled(request, db):
    """Every pre-existing test in this file exercises the automatic publish
    path and predates the supervised-mode gate — seed `auto_publish_enabled
    = "true"` by default so they keep testing what they were written for.
    `TestSupervisedModeGate` explicitly seeds its own values and opts out of
    this default."""
    if request.cls is not None and request.cls.__name__ == "TestSupervisedModeGate":
        return
    db.add(MlBotConfig(clave="auto_publish_enabled", valor="true", tipo="bool"))
    db.flush()


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

    def test_pending_morning_row_is_never_published(self, db) -> None:
        row = _seed_question(db, status="pending_morning")
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 0
        post_answer.assert_not_called()
        db.refresh(row)
        assert row.status == "pending_morning"


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


class TestSseEmission:
    """Slice G: terminal transitions fire a lightweight `ml_bot:questions`
    reload-hint event (ADR-8). Failure to publish must never break the
    pipeline, so `sse_publish_bg` is asserted only for its call, not awaited."""

    def test_publish_success_emits_reload_hint(self, db) -> None:
        _seed_question(db)
        db.commit()

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.sse_publish_bg") as mock_sse,
        ):
            asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        mock_sse.assert_called_once_with("ml_bot:questions", {"hint": "reload"})

    def test_permanent_failure_emits_reload_hint(self, db) -> None:
        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(side_effect=AnswerPostPermanentError(row.ml_question_id, 422, "rejected"))

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.sse_publish_bg") as mock_sse,
        ):
            asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        mock_sse.assert_called_once_with("ml_bot:questions", {"hint": "reload"})


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

    def test_row_that_burned_drafting_retries_gets_full_publish_budget(self, db) -> None:
        """Judgment Day fix: a row that reset `attempts` to 0 upon entering
        `waiting` (regardless of how many drafting retries it burned) must
        get the FULL `_MAX_ATTEMPTS` publish claim budget — survive two
        transient failures and still allow a third claim/post attempt."""
        row = _seed_question(db, attempts=0)
        db.commit()
        post_answer = AsyncMock(return_value=None)

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())
        assert stats["retry"] == 1
        db.refresh(row)
        assert row.status == "waiting"
        assert row.attempts == 1

        get_question = AsyncMock(return_value={"status": "UNANSWERED"})
        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())
        assert stats["retry"] == 1
        db.refresh(row)
        assert row.status == "waiting"
        assert row.attempts == 2

        post_answer_success = AsyncMock(return_value={"id": 999})
        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer_success),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())
        assert stats["published"] == 1
        db.refresh(row)
        assert row.status == "published"

    def test_exhausted_retries_marks_failed(self, db) -> None:
        row = _seed_question(db, attempts=publisher_service._MAX_ATTEMPTS - 1)
        db.commit()
        post_answer = AsyncMock(return_value=None)
        # attempts (claim count) will be > 1 after this claim -> the
        # publisher verifies via get_question BEFORE re-posting (Judgment
        # Day fix 1b); unanswered means it proceeds.
        get_question = AsyncMock(return_value={"status": "UNANSWERED"})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"
        assert row.attempts == publisher_service._MAX_ATTEMPTS


class TestRetryVerificationBeforeRepost:
    """Judgment Day slice E round 1, fix 1(b): a row whose `attempts > 0` may
    have already been posted successfully to ML before a crash prevented the
    terminal DB write. Before re-posting, the publisher must verify via
    `get_question` first."""

    def test_crash_after_success_is_detected_and_marked_published_without_repost(self, db) -> None:
        row = _seed_question(db, attempts=1)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value={"status": "ANSWERED", "answer": {"text": "ya respondida"}})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        post_answer.assert_not_called()
        get_question.assert_awaited_once_with(row.ml_question_id)
        db.refresh(row)
        assert row.status == "published"

    def test_retry_with_unanswered_verification_posts_normally(self, db) -> None:
        row = _seed_question(db, attempts=1)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value={"status": "UNANSWERED"})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        post_answer.assert_awaited_once()
        db.refresh(row)
        assert row.status == "published"

    def test_retry_with_transient_verification_failure_does_not_post_and_is_retried(self, db) -> None:
        row = _seed_question(db, attempts=1)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value=None)

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        db.refresh(row)
        assert row.status == "waiting"
        # Judgment Day round 2 fix 1: the "penalty" for this attempt was
        # already applied atomically by the CLAIM itself (attempts:
        # 1 -> 2); the revert-on-transient-GET-failure path does not touch
        # `attempts` again, but the claim counter still bounds the loop.
        assert row.attempts == 2

    def test_first_ever_claim_posts_without_get_question(self, db) -> None:
        """Judgment Day round 2 fix 1: the first-ever claim on a row bumps
        `attempts` to 1 inside the CAS claim itself; with attempts == 1
        the publisher posts directly — no wasted verification GET."""
        row = _seed_question(db, attempts=0)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value=None)

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        get_question.assert_not_called()
        post_answer.assert_awaited_once()
        assert stats["published"] == 1
        db.refresh(row)
        assert row.status == "published"
        assert row.attempts == 1

    def test_crash_after_first_attempt_post_success_never_double_posts(self, db) -> None:
        """Judgment Day round 2 fix 1 — closes the first-attempt-crash
        double-post hole: a row claimed once (attempts -> 1), POSTed
        successfully to ML, but crashed before the terminal DB write is
        reclaimed (still `attempts == 1`, status back to `waiting` via
        stale-claim reclaim). The NEXT claim bumps attempts to 2, which
        must trigger verification-before-repost and detect the already-
        answered question WITHOUT posting a second time."""
        row = _seed_question(db, status="waiting", attempts=1)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value={"status": "ANSWERED", "answer": {"text": "ya respondida"}})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        get_question.assert_awaited_once_with(row.ml_question_id)
        assert stats["published"] == 1
        db.refresh(row)
        assert row.status == "published"
        assert row.attempts == 2

    def test_row_at_max_attempts_is_not_claimed_again_and_becomes_failed(self, db) -> None:
        """The claim counter bounds the verify-revert loop: once a row has
        been claimed `_MAX_ATTEMPTS` times, it is routed straight to
        `failed` by `_fetch_due_ids` instead of being claimed (and
        re-verified/re-reverted) again."""
        row = _seed_question(db, attempts=publisher_service._MAX_ATTEMPTS)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(return_value={"status": "UNANSWERED"})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        get_question.assert_not_called()
        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"
        assert row.attempts == publisher_service._MAX_ATTEMPTS

    def test_question_not_found_during_verification_marks_failed_immediately(self, db) -> None:
        """QuestionNotFoundError on the verification GET (question deleted
        on ML) is terminal — the row goes straight to `failed`, not another
        retry loop."""
        from app.services.ml_api_client import QuestionNotFoundError

        row = _seed_question(db, attempts=1)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})
        get_question = AsyncMock(side_effect=QuestionNotFoundError(row.ml_question_id))

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"


class TestErrorTaxonomy:
    """Judgment Day slice E round 1, fix 2: permanent 4xx errors must not
    burn bounded retries — the row goes straight to `failed`."""

    def test_permanent_error_marks_failed_immediately_without_burning_attempts(self, db) -> None:
        row = _seed_question(db, attempts=0)
        db.commit()
        post_answer = AsyncMock(side_effect=AnswerPostPermanentError(row.ml_question_id, 403, "forbidden"))

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"
        assert "403" in row.last_error
        assert row.attempts < publisher_service._MAX_ATTEMPTS

    def test_transient_5xx_is_retried_not_marked_failed(self, db) -> None:
        row = _seed_question(db, attempts=0)
        db.commit()
        post_answer = AsyncMock(return_value=None)

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["retry"] == 1
        db.refresh(row)
        assert row.status == "waiting"


class TestClaimBumpsUpdatedAt:
    def test_claim_bumps_updated_at(self, db) -> None:
        stale_updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = _seed_question(db, updated_at=stale_updated_at)
        db.commit()
        before_claim = datetime.now(timezone.utc)

        with _patch_db(db):
            claimed = publisher_service._claim_for_publishing(row.id)

        assert claimed is True
        db.refresh(row)
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        assert updated_at >= before_claim - timedelta(seconds=5)


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


class TestSupervisedModeGate:
    """Supervised mode: when `auto_publish_enabled` is not exactly "true",
    the automatic due-row selection in `run_ml_questions_publish_cycle` is
    skipped entirely. `publish_question_now` (the panel's explicit human
    action) and the stale-claim reclaim must both keep working regardless."""

    def test_disabled_by_default_skips_automatic_due_selection(self, db) -> None:
        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        assert stats["published"] == 0
        assert stats.get("supervised_skip") is True
        db.refresh(row)
        assert row.status == "waiting"

    def test_malformed_config_value_still_skips(self, db) -> None:
        db.add(MlBotConfig(clave="auto_publish_enabled", valor="maybe", tipo="bool"))
        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_not_called()
        assert stats["published"] == 0
        db.refresh(row)
        assert row.status == "waiting"

    def test_exactly_true_enables_automatic_due_selection(self, db) -> None:
        db.add(MlBotConfig(clave="auto_publish_enabled", valor="true", tipo="bool"))
        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        post_answer.assert_awaited_once()
        assert stats["published"] == 1
        assert "supervised_skip" not in stats
        db.refresh(row)
        assert row.status == "published"

    def test_stale_claim_reclaim_still_runs_when_supervised(self, db) -> None:
        stale_threshold = datetime.now(timezone.utc) - timedelta(
            minutes=publisher_service._PUBLISHING_STALE_MINUTES + 5
        )
        row = _seed_question(db, status="publishing", updated_at=stale_threshold)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        db.refresh(row)
        assert row.status == "waiting"

    def test_publish_question_now_works_when_supervised(self, db) -> None:
        row = _seed_question(db, status="taken_over", attempts=0)
        db.commit()
        post_answer = AsyncMock(return_value={"id": 999})

        # publish_question_now expects the row already CAS'd into `waiting`
        # by the router before it's invoked; simulate that directly here
        # since this test targets the gate, not the router.
        db.execute(MlBotQuestion.__table__.update().where(MlBotQuestion.id == row.id).values(status="waiting"))
        db.commit()

        with _patch_db(db), patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer):
            outcome = asyncio.run(publisher_service.publish_question_now(row.id))

        assert outcome == "published"
        post_answer.assert_awaited_once()
        db.refresh(row)
        assert row.status == "published"


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


class TestFewshotCapture:
    """T-4: dynamic few-shot capture hook (sdd/ml-bot-dynamic-fewshot, PR2,
    design "Decision: Capture side-effect placement"). Best-effort,
    dark-launched behind `fewshot_capture_enabled` (default False)."""

    def _enable_capture(self, db) -> None:
        db.add(MlBotConfig(clave="fewshot_capture_enabled", valor="true", tipo="bool"))
        db.flush()

    def test_capture_enabled_and_embed_ok_inserts_history_row(self, db) -> None:
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        self._enable_capture(db)
        row = _seed_question(db, drafted_answer="Sí, tenemos stock disponible.")
        db.commit()

        embed_passage = AsyncMock(return_value=[0.1] * 384)

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        history = db.query(MlBotAnswerHistory).filter_by(item_id=row.item_id).all()
        assert len(history) == 1
        entry = history[0]
        assert entry.question_text == row.question_text
        assert entry.answer_text == "Sí, tenemos stock disponible."
        assert entry.item_id == row.item_id
        assert entry.edited_flag is False
        assert entry.active is True

    def test_capture_disabled_by_default_no_history_row(self, db) -> None:
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        _seed_question(db)
        db.commit()

        embed_passage = AsyncMock(return_value=[0.1] * 384)

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        embed_passage.assert_not_called()
        assert db.query(MlBotAnswerHistory).count() == 0

    def test_embed_returns_none_skips_capture_publish_unaffected(self, db) -> None:
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        self._enable_capture(db)
        _seed_question(db)
        db.commit()

        embed_passage = AsyncMock(return_value=None)

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        assert db.query(MlBotAnswerHistory).count() == 0

    def test_capture_exception_is_swallowed_publish_still_succeeds(self, db) -> None:
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        self._enable_capture(db)
        _seed_question(db)
        db.commit()

        embed_passage = AsyncMock(side_effect=RuntimeError("embedder exploded"))

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        assert db.query(MlBotAnswerHistory).count() == 0

    def test_edited_flag_true_for_human_answer_source(self, db) -> None:
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        self._enable_capture(db)
        row = _seed_question(db)
        db.execute(MlBotQuestion.__table__.update().where(MlBotQuestion.id == row.id).values(answer_source="human"))
        db.commit()

        embed_passage = AsyncMock(return_value=[0.1] * 384)

        with (
            _patch_db(db),
            patch(
                "app.services.ml_questions.publisher_service.ml_client.post_answer",
                new=AsyncMock(return_value={"id": 999}),
            ),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        entry = db.query(MlBotAnswerHistory).filter_by(item_id=row.item_id).one()
        assert entry.edited_flag is True

    def test_already_answered_post_error_does_not_capture(self, db) -> None:
        """`QuestionAlreadyAnsweredError` from `post_answer` means ML already
        had an answer BEFORE our POST landed (someone/something else
        answered first) — our `drafted_answer` was never actually published,
        so this is the idempotent "no fresh publish" path (design ADR-3) and
        must NOT be captured."""
        from app.models.ml_bot_answer_history import MlBotAnswerHistory
        from app.services.ml_api_client import QuestionAlreadyAnsweredError

        self._enable_capture(db)
        row = _seed_question(db)
        db.commit()
        post_answer = AsyncMock(side_effect=QuestionAlreadyAnsweredError(row.ml_question_id))
        embed_passage = AsyncMock(return_value=[0.1] * 384)

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.post_answer", new=post_answer),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        embed_passage.assert_not_called()
        assert db.query(MlBotAnswerHistory).count() == 0

    def test_retry_verification_already_answered_path_does_not_capture(self, db) -> None:
        """The genuine idempotent short-circuit ADR-3 refers to: a row
        reclaimed after attempts > 1 whose retry-verification `get_question`
        confirms it's already answered on ML — no fresh POST of our
        drafted_answer ever happened, so nothing should be captured."""
        from app.models.ml_bot_answer_history import MlBotAnswerHistory

        self._enable_capture(db)
        _seed_question(db, attempts=2)
        db.commit()

        embed_passage = AsyncMock(return_value=[0.1] * 384)
        get_question = AsyncMock(return_value={"status": "ANSWERED", "answer": {"text": "ya respondida"}})

        with (
            _patch_db(db),
            patch("app.services.ml_questions.publisher_service.ml_client.get_question", new=get_question),
            patch("app.services.ml_questions.publisher_service.embed_passage", new=embed_passage),
        ):
            stats = asyncio.run(publisher_service.run_ml_questions_publish_cycle())

        assert stats["published"] == 1
        embed_passage.assert_not_called()
        assert db.query(MlBotAnswerHistory).count() == 0
