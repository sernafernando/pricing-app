"""Tests for the activity drain cron entry point (ml-activity-receiver,
slice 4).

The flag gate lives inside `activity_receiver_service.drain_activity`, so
these tests prove the SCRIPT never bypasses it, and that the cron log --
which is where ops actually looks -- distinguishes the outcomes instead of
collapsing them into one cheerful line.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.core.config import settings
from app.scripts import drain_ml_activity
from app.services.ml_orders_ingestion import activity_receiver_service
from app.services.ml_orders_ingestion.activity_receiver_service import ActivityDrainResult


class TestFlagGate:
    def test_main_is_a_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        with patch.object(activity_receiver_service.ml_webhook_client, "get_activity") as mock_activity:
            drain_ml_activity.main()
        mock_activity.assert_not_called()

    def test_main_calls_drain_activity(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(drain_ml_activity, "drain_activity") as mock_drain:
            mock_drain.return_value = ActivityDrainResult(ran=True)
            drain_ml_activity.main()
        mock_drain.assert_called_once()


class TestTheLogDistinguishesTheOutcomes:
    """Four different things hide behind "the drain finished": it did not
    run, it failed, it was truncated by the order-fetch budget, or it
    genuinely completed. A log that reads the same for all four is how a
    receiver that stopped working goes unnoticed."""

    def _run_and_capture(self, caplog, result) -> str:
        with patch.object(drain_ml_activity, "drain_activity", return_value=result):
            with caplog.at_level(logging.INFO):
                drain_ml_activity.main()
        return caplog.text

    def test_a_truncated_pass_is_not_reported_as_complete(self, caplog) -> None:
        result = ActivityDrainResult(ran=True, budget_exhausted=True, pages_walked=2)

        text = self._run_and_capture(caplog, result)

        assert "stopped early" in text
        assert "drain complete" not in text

    def test_a_finished_pass_says_so(self, caplog) -> None:
        result = ActivityDrainResult(ran=True, pages_walked=1, orders_resolved=3)

        text = self._run_and_capture(caplog, result)

        assert "drain complete" in text
        assert "stopped early" not in text

    def test_a_failure_is_logged_as_an_error_not_a_summary(self, caplog) -> None:
        result = ActivityDrainResult(ran=True, error="bridge rejected activity_cursor")

        with patch.object(drain_ml_activity, "drain_activity", return_value=result):
            with caplog.at_level(logging.INFO):
                drain_ml_activity.main()

        assert "bridge rejected activity_cursor" in caplog.text
        assert any(r.levelno >= logging.ERROR for r in caplog.records)
        # A failed pass must not also print the counters summary, which
        # reads like a successful run to anyone skimming the log.
        assert "drain complete" not in caplog.text

    def test_not_running_names_the_lock_as_a_possible_reason(self, caplog) -> None:
        """`ran=False` covers the flag being off AND another pass holding
        the lock. Since the ping and this cron both drain, the lock case
        is the routine one -- a log that only ever blames the flag sends
        whoever reads it to check the wrong thing."""
        text = self._run_and_capture(caplog, ActivityDrainResult(ran=False))

        assert "did not run" in text
        assert "lock" in text

    def test_the_unresolved_and_not_attempted_counters_both_reach_the_log(self, caplog) -> None:
        """These two are deliberately distinct in the service (an order ML
        answered "no" to versus one the budget never reached). Collapsing
        them in the log throws that distinction away right where an
        operator would use it."""
        result = ActivityDrainResult(ran=True, orders_unresolved=2, orders_not_attempted=7)

        text = self._run_and_capture(caplog, result)

        assert "unresolved=2" in text
        assert "not_attempted=7" in text


class TestTheAlarmFiresOnlyOnWhatNothingExplains:
    """A pass that resolved orders and wrote none of them is how the
    field-name mismatch hid for a week, so it has to shout. But two
    outcomes explain a missing write with nothing wrong -- an order we
    already hold at that version, and one the rolling window excludes by
    design. Alarming on those makes the alarm routine, and a routine
    alarm is one nobody reads the next time it matters.
    """

    def _run(self, caplog, **counters) -> tuple[str, bool]:
        result = ActivityDrainResult(ran=True, **counters)
        with patch.object(drain_ml_activity, "drain_activity", return_value=result):
            with caplog.at_level(logging.INFO):
                drain_ml_activity.main()
        return caplog.text, any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_all_stale_is_not_an_alarm(self, caplog) -> None:
        _, alarmed = self._run(caplog, orders_resolved=5, orders_skipped_stale=5)

        assert alarmed is False

    def test_all_out_of_window_is_not_an_alarm(self, caplog) -> None:
        _, alarmed = self._run(caplog, orders_resolved=5, orders_out_of_window=5)

        assert alarmed is False

    def test_a_mix_that_adds_up_is_not_an_alarm(self, caplog) -> None:
        _, alarmed = self._run(
            caplog, orders_resolved=6, orders_upserted=2, orders_skipped_stale=3, orders_out_of_window=1
        )

        assert alarmed is False

    def test_orders_nothing_accounts_for_do_alarm(self, caplog) -> None:
        """The bug exactly: fetched, mapped, dropped."""
        text, alarmed = self._run(caplog, orders_resolved=5, orders_mapping_error=5)

        assert alarmed is True
        assert "not ingesting" in text

    def test_a_partial_hole_alarms_even_when_some_were_written(self, caplog) -> None:
        """Four written, one gone. The one that vanished is the whole
        point -- a pass is not healthy just because it was mostly healthy."""
        text, alarmed = self._run(caplog, orders_resolved=5, orders_upserted=4)

        assert alarmed is True
        assert "1 of 5" in text
