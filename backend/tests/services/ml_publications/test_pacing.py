"""Shared ML budget: 2 req/s global, stock sub-budget, 429 cooldown, AIMD (design D11).

All timing runs on an injected fake clock: no test sleeps for real.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from app.services.ml_publications.pacing import DEADLINE, GRANTED, MAX_COOLDOWN_SECONDS, Pacer

T0 = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """Monotonic clock whose `sleep` advances time; records every sleep."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.t += seconds

    def now(self) -> datetime:
        return T0 + timedelta(seconds=self.t - 1000.0)

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def make(clock: FakeClock, **kwargs) -> Pacer:
    kwargs.setdefault("rng", random.Random(7))
    return Pacer(clock=clock, **kwargs)


def grant_times(pacer: Pacer, clock: FakeClock, families: list[str]) -> list[float]:
    times = []
    for family in families:
        assert pacer.acquire(family) == GRANTED
        times.append(clock.monotonic())
    return times


class TestGlobalBudget:
    def test_two_per_second_is_never_exceeded_over_100_calls(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        times = grant_times(pacer, clock, ["items_bulk"] * 100)
        assert len(times) == 100
        # No 1-second window ever holds more than 2 calls.
        assert all(times[i + 2] - times[i] >= 1.0 - 1e-9 for i in range(len(times) - 2))
        assert times[-1] - times[0] == pytest.approx(99 * 0.5)

    def test_rate_is_configurable(self, clock) -> None:
        pacer = make(clock, rate_per_sec=5.0)
        times = grant_times(pacer, clock, ["items_bulk"] * 11)
        assert times[-1] - times[0] == pytest.approx(10 * 0.2)

    def test_configure_applies_a_new_rate_to_the_next_calls(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        grant_times(pacer, clock, ["items_bulk"] * 2)
        pacer.configure(rate_per_sec=1.0, stock_rate_per_min=60)
        times = grant_times(pacer, clock, ["items_bulk"] * 3)
        assert times[2] - times[1] == pytest.approx(1.0)


class TestStockSubBudget:
    def test_stock_calls_stay_at_or_below_the_documented_100_per_minute(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0, stock_rate_per_min=60)
        times = grant_times(pacer, clock, ["stock"] * 130)
        in_any_minute = max(sum(1 for u in times if t <= u < t + 60.0) for t in times)
        assert in_any_minute <= 60
        assert times[1] - times[0] == pytest.approx(1.0)

    def test_stock_limit_does_not_slow_other_endpoints(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0, stock_rate_per_min=60)
        times = grant_times(pacer, clock, ["items_bulk"] * 20)
        assert times[-1] - times[0] == pytest.approx(19 * 0.5)

    def test_stock_calls_also_spend_the_global_budget(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0, stock_rate_per_min=100)
        families = ["stock", "items_bulk"] * 30
        times = grant_times(pacer, clock, families)
        assert all(times[i + 2] - times[i] >= 1.0 - 1e-9 for i in range(len(times) - 2))
        stock_times = times[0::2]
        assert all(b - a >= 0.6 - 1e-9 for a, b in zip(stock_times, stock_times[1:]))

    def test_stock_budget_above_the_documented_limit_is_rejected(self, clock) -> None:
        with pytest.raises(ValueError):
            make(clock, stock_rate_per_min=101)


class TestRateLimited:
    def test_retry_after_seconds_blocks_the_job_for_at_least_that_long(self, clock) -> None:
        pacer = make(clock)
        assert pacer.acquire("items_bulk") == GRANTED
        start = clock.monotonic()
        assert pacer.on_rate_limited("30") == 30.0
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - start >= 30.0

    def test_retry_after_http_date_is_parsed(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() + timedelta(seconds=45), usegmt=True)
        assert pacer.on_rate_limited(header) == pytest.approx(45.0)
        start = clock.monotonic()
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - start >= 45.0

    def test_http_date_in_the_past_means_no_extra_wait(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() - timedelta(seconds=10), usegmt=True)
        assert pacer.on_rate_limited(header) == 0.0

    @pytest.mark.parametrize("header", [None, "", "soon", "-5"])
    def test_missing_or_unusable_header_uses_exponential_backoff_with_jitter(self, clock, header) -> None:
        pacer = make(clock)
        delays = [pacer.on_rate_limited(header) for _ in range(10)]
        for n, delay in enumerate(delays, start=1):
            cap = min(2.0**n, 60.0)
            assert 0.5 * cap - 1e-9 <= delay <= cap + 1e-9
        assert max(delays) <= 60.0
        assert delays[-1] > 30.0  # the exponent actually grew

    def test_success_resets_the_backoff_exponent(self, clock) -> None:
        pacer = make(clock)
        for _ in range(5):
            pacer.on_rate_limited(None)
        pacer.on_success()
        assert pacer.on_rate_limited(None) <= 2.0

    @pytest.mark.parametrize("header", ["999999", "86400"])
    def test_an_absurd_retry_after_is_capped_so_the_job_is_never_parked_for_days(self, clock, header) -> None:
        pacer = make(clock)
        assert pacer.on_rate_limited(header) == MAX_COOLDOWN_SECONDS == 3600.0
        assert pacer.cooldown_remaining() == pytest.approx(3600.0)
        before = clock.monotonic()
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - before == pytest.approx(3600.0)

    def test_an_http_date_far_in_the_future_is_capped_too(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() + timedelta(days=3), usegmt=True)
        assert pacer.on_rate_limited(header) == MAX_COOLDOWN_SECONDS

    def test_a_longer_existing_cooldown_is_never_shortened(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("120")
        pacer.on_rate_limited("5")
        assert pacer.cooldown_remaining() == pytest.approx(120.0)


class TestAimd:
    def test_429_halves_the_effective_rate_for_ten_minutes_then_restores_stepwise(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        assert pacer.effective_rate() == 2.0
        pacer.on_rate_limited("1")
        assert pacer.effective_rate() == 1.0
        clock.advance(599)
        assert pacer.effective_rate() == 1.0
        clock.advance(61)  # 660 s after the 429: first restore step
        assert 1.0 < pacer.effective_rate() < 2.0
        clock.advance(600)
        assert pacer.effective_rate() == 2.0

    def test_halved_rate_spaces_calls_twice_as_far_apart(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        pacer.on_rate_limited("0")
        times = grant_times(pacer, clock, ["items_bulk"] * 3)
        assert times[2] - times[1] == pytest.approx(1.0)

    def test_repeated_429s_keep_halving_down_to_a_floor(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        for _ in range(10):
            pacer.on_rate_limited("0")
        assert pacer.effective_rate() == pytest.approx(2.0 / 16)


class TestDeadline:
    def test_never_sleeps_past_the_deadline(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("30")
        before = clock.monotonic()
        assert pacer.acquire("items_bulk", deadline=clock.now() + timedelta(seconds=10)) == DEADLINE
        assert clock.monotonic() == before
        assert clock.sleeps == []

    def test_a_naive_deadline_is_rejected_instead_of_failing_mid_subtraction(self, clock) -> None:
        pacer = make(clock)
        with pytest.raises(ValueError, match="timezone"):
            pacer.acquire("items_bulk", deadline=datetime(2026, 10, 6, 12, 0, 30))

    def test_a_deadline_beyond_the_wait_is_granted_after_sleeping(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("30")
        assert pacer.acquire("items_bulk", deadline=clock.now() + timedelta(seconds=60)) == GRANTED
        assert clock.sleeps and sum(clock.sleeps) >= 30.0

    def test_bucket_wait_longer_than_the_remaining_time_returns_deadline_without_consuming(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        assert pacer.acquire("items_bulk") == GRANTED
        deadline = clock.now() + timedelta(seconds=0.1)  # next slot is 0.5 s away
        assert pacer.acquire("items_bulk", deadline=deadline) == DEADLINE
        assert pacer.acquire("items_bulk") == GRANTED  # the refused call did not eat the slot
        assert clock.monotonic() - 1000.0 == pytest.approx(0.5)
