"""Shared ML budget: 2 req/s global, stock sub-budget, 429 cooldown, AIMD (design D11).

All timing runs on an injected fake clock: no test sleeps for real.
"""

from __future__ import annotations

import random
import threading
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
        assert pacer.on_rate_limited("items_bulk", "30") == 30.0
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - start >= 30.0

    def test_retry_after_http_date_is_parsed(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() + timedelta(seconds=45), usegmt=True)
        assert pacer.on_rate_limited("items_bulk", header) == pytest.approx(45.0)
        start = clock.monotonic()
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - start >= 45.0

    def test_http_date_in_the_past_means_no_extra_wait(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() - timedelta(seconds=10), usegmt=True)
        assert pacer.on_rate_limited("items_bulk", header) == 0.0

    @pytest.mark.parametrize("header", [None, "", "soon", "-5"])
    def test_missing_or_unusable_header_uses_exponential_backoff_with_jitter(self, clock, header) -> None:
        pacer = make(clock)
        delays = [pacer.on_rate_limited("items_bulk", header) for _ in range(10)]
        for n, delay in enumerate(delays, start=1):
            cap = min(2.0**n, 60.0)
            assert 0.5 * cap - 1e-9 <= delay <= cap + 1e-9
        assert max(delays) <= 60.0
        assert delays[-1] > 30.0  # the exponent actually grew

    def test_success_resets_the_backoff_exponent(self, clock) -> None:
        pacer = make(clock)
        for _ in range(5):
            pacer.on_rate_limited("items_bulk", None)
        pacer.on_success("items_bulk")
        assert pacer.on_rate_limited("items_bulk", None) <= 2.0

    @pytest.mark.parametrize("header", ["999999", "86400"])
    def test_an_absurd_retry_after_is_capped_so_the_job_is_never_parked_for_days(self, clock, header) -> None:
        pacer = make(clock)
        assert pacer.on_rate_limited("items_bulk", header) == MAX_COOLDOWN_SECONDS == 3600.0
        assert pacer.cooldown_remaining("items_bulk") == pytest.approx(3600.0)
        before = clock.monotonic()
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - before == pytest.approx(3600.0)

    def test_an_http_date_far_in_the_future_is_capped_too(self, clock) -> None:
        pacer = make(clock)
        header = format_datetime(clock.now() + timedelta(days=3), usegmt=True)
        assert pacer.on_rate_limited("items_bulk", header) == MAX_COOLDOWN_SECONDS

    def test_a_longer_existing_cooldown_is_never_shortened(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("items_bulk", "120")
        pacer.on_rate_limited("items_bulk", "5")
        assert pacer.cooldown_remaining("items_bulk") == pytest.approx(120.0)


class TestAimd:
    def test_429_halves_the_effective_rate_for_ten_minutes_then_restores_stepwise(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        assert pacer.effective_rate("items_bulk") == 2.0
        pacer.on_rate_limited("items_bulk", "1")
        assert pacer.effective_rate("items_bulk") == 1.0
        clock.advance(599)
        assert pacer.effective_rate("items_bulk") == 1.0
        clock.advance(61)  # 660 s after the 429: first restore step
        assert 1.0 < pacer.effective_rate("items_bulk") < 2.0
        clock.advance(600)
        assert pacer.effective_rate("items_bulk") == 2.0

    def test_halved_rate_spaces_calls_twice_as_far_apart(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        pacer.on_rate_limited("items_bulk", "0")
        times = grant_times(pacer, clock, ["items_bulk"] * 3)
        assert times[2] - times[1] == pytest.approx(1.0)

    def test_repeated_429s_keep_halving_down_to_a_floor(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        for _ in range(10):
            pacer.on_rate_limited("items_bulk", "0")
        assert pacer.effective_rate("items_bulk") == pytest.approx(2.0 / 16)


class TestDeadline:
    def test_never_sleeps_past_the_deadline(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("items_bulk", "30")
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
        pacer.on_rate_limited("items_bulk", "30")
        assert pacer.acquire("items_bulk", deadline=clock.now() + timedelta(seconds=60)) == GRANTED
        assert clock.sleeps and sum(clock.sleeps) >= 30.0

    def test_bucket_wait_longer_than_the_remaining_time_returns_deadline_without_consuming(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        assert pacer.acquire("items_bulk") == GRANTED
        deadline = clock.now() + timedelta(seconds=0.1)  # next slot is 0.5 s away
        assert pacer.acquire("items_bulk", deadline=deadline) == DEADLINE
        assert pacer.acquire("items_bulk") == GRANTED  # the refused call did not eat the slot
        assert clock.monotonic() - 1000.0 == pytest.approx(0.5)


class TestRateLimitedPerFamily:
    """ML limits per Client ID and per endpoint: a 429 on one endpoint family cools down that family only; every
    family keeps spending the one global budget (owner, 2026-10-26: "pero por qué hacemos las llamadas en serie?")."""

    def test_a_429_cools_down_only_its_family(self, clock) -> None:
        pacer = make(clock)
        pacer.on_rate_limited("items_bulk", "30")
        start = clock.monotonic()
        assert pacer.acquire("description") == GRANTED
        assert clock.monotonic() - start < 1.0  # description does not wait out items_bulk's cooldown
        assert pacer.cooldown_remaining("description") == 0.0
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.monotonic() - start >= 30.0

    def test_a_429_halves_only_its_familys_rate(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        pacer.on_rate_limited("items_bulk", "0")
        assert pacer.effective_rate("items_bulk") == 1.0
        assert pacer.effective_rate("description") == 2.0
        times = grant_times(pacer, clock, ["description"] * 3)
        assert times[2] - times[1] == pytest.approx(0.5)
        times = grant_times(pacer, clock, ["items_bulk"] * 3)
        assert times[2] - times[1] == pytest.approx(1.0)

    def test_the_backoff_exponent_is_per_family(self, clock) -> None:
        pacer = make(clock)
        for _ in range(5):
            pacer.on_rate_limited("items_bulk", None)
        pacer.on_success("description")  # another family's success does not reset items_bulk's exponent
        assert pacer.on_rate_limited("items_bulk", None) > 30.0
        assert pacer.on_rate_limited("description", None) <= 2.0

    def test_families_still_share_the_global_ceiling(self, clock) -> None:
        pacer = make(clock, rate_per_sec=2.0)
        pacer.on_rate_limited("items_bulk", "0")
        times = grant_times(pacer, clock, ["description", "prices", "promotions", "stock"] * 10)
        assert all(times[i + 2] - times[i] >= 1.0 - 1e-9 for i in range(len(times) - 2))


class StillClock(FakeClock):
    """Time never moves: `sleep` only records, so every caller's wait shows the slot it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()

    def sleep(self, seconds: float) -> None:
        with self.lock:
            self.sleeps.append(seconds)


class TestConcurrentCallers:
    """Calls run concurrently (ml-sync-pipeline S3): each caller is given its own slot before it sleeps, so callers
    that ask at the same moment are spread over the budget instead of waking up together."""

    def test_callers_asking_at_once_get_consecutive_slots(self) -> None:
        clock = StillClock()
        pacer = Pacer(clock=clock, rate_per_sec=2.0, rng=random.Random(7))
        assert pacer.acquire("items_bulk") == GRANTED
        assert pacer.acquire("items_bulk") == GRANTED
        assert pacer.acquire("items_bulk") == GRANTED
        assert clock.sleeps == [pytest.approx(0.5), pytest.approx(1.0)]

    def test_threads_never_share_a_slot(self) -> None:
        clock = StillClock()
        pacer = Pacer(clock=clock, rate_per_sec=2.0, rng=random.Random(7))
        start = threading.Barrier(16)

        def call(family: str) -> None:
            start.wait()
            for _ in range(10):
                assert pacer.acquire(family) == GRANTED

        threads = [threading.Thread(target=call, args=(f,)) for f in ["items_bulk", "description"] * 8]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # 160 calls at t=0: one is granted at once, the others wait 0.5, 1.0, ... 79.5 s, each slot once.
        assert sorted(clock.sleeps) == pytest.approx([0.5 * k for k in range(1, 160)])

    def test_a_slot_given_before_a_429_waits_out_its_familys_cooldown(self) -> None:
        clock = FakeClock()
        pacer = Pacer(clock=clock, rate_per_sec=2.0, rng=random.Random(7))
        assert pacer.acquire("items_bulk") == GRANTED

        def throttled_sleep(seconds: float, sleep=clock.sleep) -> None:
            sleep(seconds)
            if len(clock.sleeps) == 1:  # the 429 lands while this caller sleeps toward its slot
                pacer.on_rate_limited("items_bulk", "30")

        clock.sleep = throttled_sleep
        start = clock.monotonic()
        assert pacer.acquire("items_bulk", deadline=clock.now() + timedelta(seconds=60)) == GRANTED
        assert clock.monotonic() - start >= 30.0


class HeldClock(FakeClock):
    """The thread named "held" blocks inside its sleep until released, so another caller acts while it waits."""

    def __init__(self) -> None:
        super().__init__()
        self.waiting = threading.Event()
        self.release = threading.Event()

    def sleep(self, seconds: float) -> None:
        if threading.current_thread().name == "held":
            self.waiting.set()
            self.release.wait(5)
        super().sleep(seconds)


class TestAWaitingFamilyHoldsNoGlobalSlot:
    """A caller waiting out its family's cooldown or penalty holds no global slot, so the other families keep
    calling meanwhile (verifier B1: a queued caller of a throttled family made every family wait behind it)."""

    def _other_family_waits_while_held(self, pacer: Pacer, clock: HeldClock) -> float:
        held = threading.Thread(target=lambda: pacer.acquire("items_bulk"), name="held")
        held.start()
        assert clock.waiting.wait(5)
        start = clock.monotonic()
        assert pacer.acquire("description") == GRANTED
        waited = clock.monotonic() - start
        clock.release.set()
        held.join(5)
        return waited

    def test_during_a_cooldown(self) -> None:
        clock = HeldClock()
        pacer = Pacer(clock=clock, rng=random.Random(7))
        pacer.on_rate_limited("items_bulk", "30")
        assert self._other_family_waits_while_held(pacer, clock) < 1.0

    def test_during_a_penalty(self) -> None:
        clock = HeldClock()
        pacer = Pacer(clock=clock, rate_per_sec=2.0, rng=random.Random(7))
        for _ in range(4):
            pacer.on_rate_limited("items_bulk", "0")  # items_bulk now at 1/16 of the rate: one call every 8 s
        assert pacer.acquire("items_bulk") == GRANTED
        assert self._other_family_waits_while_held(pacer, clock) < 1.0
