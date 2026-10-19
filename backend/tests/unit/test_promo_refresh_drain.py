"""The decisions of the `promo_refresh_pending` drain, without a database.

The Postgres tests in tests/workers/handlers/test_promo_refresh.py prove the queries and commits; these pin the
pure rules (kill switch, settle decision, stale cutoff) and the per-row isolation of the pass, and never skip.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from app.core.config import settings
from app.services import promo_refresh_drain as drain
from app.services.ml_webhook_client import RefreshOutcome, ml_webhook_client

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture()
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROMOS_WRITE_ENABLED", True)


@contextmanager
def _session():
    yield object()


class TestKillSwitch:
    def test_off_opens_no_session_and_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "PROMOS_WRITE_ENABLED", False)
        sessions = mock.Mock(side_effect=AssertionError("a session was opened"))

        with mock.patch.object(ml_webhook_client, "refresh_item_promotions") as call:
            result = drain.drain(deadline=None, session_factory=sessions)

        assert result == {"skipped": "PROMOS_WRITE_ENABLED is off"}
        sessions.assert_not_called()
        call.assert_not_called()


class TestDecide:
    def test_a_success_is_refreshed(self) -> None:
        assert drain.decide(RefreshOutcome(ok=True), attempts=drain.MAX_ATTEMPTS) == drain.REFRESHED

    def test_a_failure_retrying_cannot_fix_is_dropped(self) -> None:
        assert drain.decide(RefreshOutcome(ok=False, reintentable=False), attempts=1) == drain.DROPPED

    def test_a_retryable_failure_under_the_cap_is_retried(self) -> None:
        assert drain.decide(RefreshOutcome(ok=False), attempts=drain.MAX_ATTEMPTS - 1) == drain.RETRY

    def test_an_exception_counts_as_a_retryable_failure(self) -> None:
        assert drain.decide(None, attempts=1) == drain.RETRY

    def test_a_retryable_failure_at_the_cap_is_quarantined(self) -> None:
        assert drain.decide(RefreshOutcome(ok=False), attempts=drain.MAX_ATTEMPTS) == drain.QUARANTINE
        assert drain.decide(None, attempts=drain.MAX_ATTEMPTS) == drain.QUARANTINE

    def test_a_retry_is_due_again_after_the_write_retry_delay(self) -> None:
        assert drain.retry_due_at(NOW) == NOW + timedelta(seconds=60)


class TestStaleCutoff:
    def test_a_row_due_more_than_24_hours_ago_is_stale(self) -> None:
        assert drain.is_stale(NOW - timedelta(hours=24, seconds=1), NOW) is True

    def test_a_row_due_exactly_24_hours_ago_is_not_stale(self) -> None:
        assert drain.is_stale(NOW - timedelta(hours=24), NOW) is False

    def test_a_row_due_recently_or_in_the_future_is_not_stale(self) -> None:
        assert drain.is_stale(NOW - timedelta(minutes=5), NOW) is False
        assert drain.is_stale(NOW + timedelta(minutes=5), NOW) is False


class TestRefreshCall:
    def test_an_exception_from_the_client_becomes_none_and_is_logged(self, caplog) -> None:
        with mock.patch.object(ml_webhook_client, "refresh_item_promotions", side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.WARNING):
                assert drain._refresh("MLA1") is None
        assert "refresh_item_promotions raised for MLA1" in caplog.text

    def test_the_outcome_of_the_client_is_returned(self) -> None:
        outcome = RefreshOutcome(ok=False, motivo="proxy 502")
        with mock.patch.object(ml_webhook_client, "refresh_item_promotions", new=mock.AsyncMock(return_value=outcome)):
            assert drain._refresh("MLA1") is outcome


class TestPassIsolation:
    """The pass with its DB steps stubbed: each row stands alone."""

    def _claims(self, *mlas: str):
        queue = [drain.Claim(mla, NOW) for mla in mlas]
        return lambda db, at: (queue.pop(0) if queue else None, 0)

    def test_a_failing_call_does_not_stop_the_next_row(self, enabled, monkeypatch) -> None:
        monkeypatch.setattr(drain, "purge_stale", lambda db, at: 0)
        monkeypatch.setattr(drain, "claim_one", self._claims("MLA_BAD", "MLA_GOOD"))
        monkeypatch.setattr(drain, "_refresh", lambda mla: None if mla == "MLA_BAD" else RefreshOutcome(ok=True))
        settled: list[tuple[str, object]] = []
        monkeypatch.setattr(drain, "_settle", lambda db, claim, outcome, detail: settled.append((claim.mla, outcome)))

        result = drain.drain(deadline=None, session_factory=_session)

        assert [mla for mla, _ in settled] == ["MLA_BAD", "MLA_GOOD"]
        assert settled[0][1] is None
        assert result["errors"] == 0

    def test_a_settle_error_is_counted_and_the_pass_goes_on(self, enabled, monkeypatch, caplog) -> None:
        monkeypatch.setattr(drain, "purge_stale", lambda db, at: 0)
        monkeypatch.setattr(drain, "claim_one", self._claims("MLA_BAD", "MLA_GOOD"))
        monkeypatch.setattr(drain, "_refresh", lambda mla: RefreshOutcome(ok=True))
        settled: list[str] = []

        def settle(db, claim, outcome, detail):
            if claim.mla == "MLA_BAD":
                raise RuntimeError("db down")
            settled.append(claim.mla)

        monkeypatch.setattr(drain, "_settle", settle)

        with caplog.at_level(logging.ERROR):
            result = drain.drain(deadline=None, session_factory=_session)

        assert settled == ["MLA_GOOD"]
        assert result["errors"] == 1
        assert "settling MLA_BAD failed" in caplog.text

    def test_a_purge_error_is_counted_and_due_rows_still_drain(self, enabled, monkeypatch, caplog) -> None:
        def purge(db, at):
            raise RuntimeError("statement timeout")

        monkeypatch.setattr(drain, "purge_stale", purge)
        monkeypatch.setattr(drain, "claim_one", self._claims("MLA1"))
        monkeypatch.setattr(drain, "_refresh", lambda mla: RefreshOutcome(ok=True))
        settled: list[str] = []
        monkeypatch.setattr(drain, "_settle", lambda db, claim, outcome, detail: settled.append(claim.mla))

        with caplog.at_level(logging.ERROR):
            result = drain.drain(deadline=None, session_factory=_session)

        assert settled == ["MLA1"]
        assert result["errors"] == 1
        assert result["stale_dropped"] == 0
        assert "purging stale rows failed" in caplog.text

    def test_repeated_claim_errors_stay_within_the_batch_cap(self, enabled, monkeypatch) -> None:
        monkeypatch.setattr(drain, "MAX_ROWS_PER_RUN", 3)
        monkeypatch.setattr(drain, "purge_stale", lambda db, at: 0)

        def claim_one(db, at):
            raise RuntimeError("db down")

        monkeypatch.setattr(drain, "claim_one", claim_one)

        result = drain.drain(deadline=None, session_factory=_session)

        assert result["errors"] == 3
        assert result["capped"] is True


class TestConfirmationAfterRefresh:
    """P3: once a refresh succeeded the mirror is fresh, so the drain asks whether ML applied the recent writes.
    That step is best effort and runs outside every claim/settle session."""

    def _one(self, monkeypatch, outcome) -> None:
        monkeypatch.setattr(drain, "purge_stale", lambda db, at: 0)
        queue = [drain.Claim("MLA1", NOW)]
        monkeypatch.setattr(drain, "claim_one", lambda db, at: (queue.pop(0) if queue else None, 0))
        monkeypatch.setattr(drain, "_refresh", lambda mla: outcome)

    def test_a_successful_refresh_confirms_after_the_settle_with_no_session_open(self, enabled, monkeypatch) -> None:
        self._one(monkeypatch, RefreshOutcome(ok=True))
        open_sessions = 0
        events: list[tuple[str, int]] = []

        @contextmanager
        def sessions():
            nonlocal open_sessions
            open_sessions += 1
            try:
                yield object()
            finally:
                open_sessions -= 1

        monkeypatch.setattr(
            drain, "_settle", lambda db, claim, outcome, detail: events.append(("settle", open_sessions))
        )
        monkeypatch.setattr(
            drain, "confirm_recent_writes", lambda mla, **kw: events.append((f"confirm {mla}", open_sessions)) or 0
        )

        drain.drain(deadline=None, session_factory=sessions)

        assert events == [("settle", 1), ("confirm MLA1", 0)]

    @pytest.mark.parametrize("outcome", [None, RefreshOutcome(ok=False), RefreshOutcome(ok=False, reintentable=False)])
    def test_a_failed_refresh_confirms_nothing(self, enabled, monkeypatch, outcome) -> None:
        self._one(monkeypatch, outcome)
        monkeypatch.setattr(drain, "_settle", lambda db, claim, outcome, detail: None)
        confirm = mock.Mock(return_value=0)
        monkeypatch.setattr(drain, "confirm_recent_writes", confirm)

        drain.drain(deadline=None, session_factory=_session)

        confirm.assert_not_called()

    def test_a_raising_confirmation_changes_neither_the_settle_nor_the_counts(
        self, enabled, monkeypatch, caplog
    ) -> None:
        self._one(monkeypatch, RefreshOutcome(ok=True))

        def settle(db, claim, outcome, detail):
            detail["refreshed"] += 1

        monkeypatch.setattr(drain, "_settle", settle)
        monkeypatch.setattr(drain, "confirm_recent_writes", mock.Mock(side_effect=RuntimeError("bug")))

        with caplog.at_level(logging.WARNING):
            result = drain.drain(deadline=None, session_factory=_session)

        assert result["refreshed"] == 1
        assert result["errors"] == 0
        assert "confirming writes for MLA1 failed" in caplog.text

    def _clock(self, monkeypatch, start: datetime, after_refresh: datetime) -> None:
        """The drain clock reads `start` until the refresh returns, then `after_refresh`."""
        clock = [start]
        monkeypatch.setattr(drain, "_utcnow", lambda: clock[0])

        def refresh(mla):
            clock[0] = after_refresh
            return RefreshOutcome(ok=True)

        monkeypatch.setattr(drain, "_refresh", refresh)

    def test_a_deadline_passed_during_the_refresh_settles_but_skips_the_confirmation(
        self, enabled, monkeypatch
    ) -> None:
        self._one(monkeypatch, RefreshOutcome(ok=True))
        deadline = NOW + timedelta(seconds=10)
        self._clock(monkeypatch, NOW, deadline + timedelta(seconds=1))

        def settle(db, claim, outcome, detail):
            detail["refreshed"] += 1

        monkeypatch.setattr(drain, "_settle", settle)
        confirm = mock.Mock(return_value=0)
        monkeypatch.setattr(drain, "confirm_recent_writes", confirm)

        result = drain.drain(deadline=deadline, session_factory=_session)

        assert result["refreshed"] == 1
        confirm.assert_not_called()
        assert result["confirm_skipped_deadline"] == 1

    def test_a_deadline_too_close_skips_the_confirmation(self, enabled, monkeypatch) -> None:
        self._one(monkeypatch, RefreshOutcome(ok=True))
        deadline = NOW + timedelta(seconds=10)
        self._clock(monkeypatch, NOW, deadline - drain.CONFIRM_DEADLINE_MARGIN / 2)
        monkeypatch.setattr(drain, "_settle", lambda db, claim, outcome, detail: None)
        confirm = mock.Mock(return_value=0)
        monkeypatch.setattr(drain, "confirm_recent_writes", confirm)

        result = drain.drain(deadline=deadline, session_factory=_session)

        confirm.assert_not_called()
        assert result["confirm_skipped_deadline"] == 1

    def test_a_deadline_still_ahead_runs_the_confirmation(self, enabled, monkeypatch) -> None:
        self._one(monkeypatch, RefreshOutcome(ok=True))
        deadline = NOW + timedelta(seconds=30)
        self._clock(monkeypatch, NOW, NOW + timedelta(seconds=1))
        monkeypatch.setattr(drain, "_settle", lambda db, claim, outcome, detail: None)
        confirm = mock.Mock(return_value=0)
        monkeypatch.setattr(drain, "confirm_recent_writes", confirm)

        result = drain.drain(deadline=deadline, session_factory=_session)

        confirm.assert_called_once_with("MLA1", session_factory=_session)
        assert result["confirm_skipped_deadline"] == 0
