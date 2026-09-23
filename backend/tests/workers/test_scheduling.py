"""RED/GREEN -- `JobHandler` scheduling math (ventas-ml-rediseno PR2.T1,
design D6): `interval` jobs are due when enough time elapsed since their
last success; `run_at_local` (daily wall-clock slot) jobs are due once per
local day, and a restart must never re-run today's slot twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from app.workers.scheduling import ARGENTINA_TZ, is_due


@dataclass
class _StubHandler:
    name: str
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None


class TestIntervalScheduling:
    def test_never_run_before_is_due(self) -> None:
        handler = _StubHandler(name="order_metrics.reconcile", interval=timedelta(minutes=10))
        now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        assert is_due(handler, now=now, last_success_at=None) is True

    def test_not_due_before_interval_elapsed(self) -> None:
        handler = _StubHandler(name="order_metrics.reconcile", interval=timedelta(minutes=10))
        now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        last_success = now - timedelta(minutes=5)
        assert is_due(handler, now=now, last_success_at=last_success) is False

    def test_due_once_interval_elapsed(self) -> None:
        handler = _StubHandler(name="order_metrics.reconcile", interval=timedelta(minutes=10))
        now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        last_success = now - timedelta(minutes=10)
        assert is_due(handler, now=now, last_success_at=last_success) is True


class TestDailySlotScheduling:
    def test_not_due_before_todays_slot(self) -> None:
        handler = _StubHandler(name="order_metrics.divergence", run_at_local=time(4, 0))
        # 03:59 local (AR, UTC-3) -- before today's 04:00 slot.
        now = datetime(2026, 9, 23, 6, 59, tzinfo=timezone.utc)
        assert is_due(handler, now=now, last_success_at=None) is False

    def test_due_at_or_after_todays_slot_with_no_prior_success(self) -> None:
        handler = _StubHandler(name="order_metrics.divergence", run_at_local=time(4, 0))
        now = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)  # 04:00 AR
        assert is_due(handler, now=now, last_success_at=None) is True

    def test_restart_does_not_double_run_same_slot(self) -> None:
        """A worker restarting at 04:05 AR after already succeeding at 04:01
        AR today must NOT re-run -- `last_success_at` already covers today's
        slot (design D6: "restart does not re-run daily jobs twice")."""
        handler = _StubHandler(name="order_metrics.divergence", run_at_local=time(4, 0))
        last_success = datetime(2026, 9, 23, 7, 1, tzinfo=timezone.utc)  # 04:01 AR today
        now = datetime(2026, 9, 23, 7, 5, tzinfo=timezone.utc)  # 04:05 AR, same day
        assert is_due(handler, now=now, last_success_at=last_success) is False

    def test_due_again_the_next_day_after_yesterdays_success(self) -> None:
        handler = _StubHandler(name="order_metrics.divergence", run_at_local=time(4, 0))
        last_success = datetime(2026, 9, 22, 7, 1, tzinfo=timezone.utc)  # 04:01 AR yesterday
        now = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)  # 04:00 AR today
        assert is_due(handler, now=now, last_success_at=last_success) is True

    def test_success_earlier_same_local_day_before_slot_still_lets_it_run(self) -> None:
        """A prior success on the SAME local day but BEFORE today's slot
        (e.g. an on-demand run at 02:00) must not block the scheduled 04:00
        run."""
        handler = _StubHandler(name="order_metrics.divergence", run_at_local=time(4, 0))
        last_success = datetime(2026, 9, 23, 5, 0, tzinfo=timezone.utc)  # 02:00 AR today
        now = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)  # 04:00 AR today
        assert is_due(handler, now=now, last_success_at=last_success) is True

    def test_utc_timestamps_converted_to_argentina_local_before_slot_math(self) -> None:
        assert ARGENTINA_TZ == ZoneInfo("America/Argentina/Buenos_Aires")


class TestNoSchedule:
    def test_channel_only_handler_is_never_due_by_schedule(self) -> None:
        handler = _StubHandler(name="order_metrics.drain", channels=("order_metrics_dirty",))
        now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        assert is_due(handler, now=now, last_success_at=None) is False
