"""One in-process ML budget for every call the store makes (design D11).

Callers may run concurrently (ml-sync-pipeline S3): the pacer is thread-safe and
stays an exact budget for the process. It combines:

- a global gate (`rate_per_sec`, default 2/s) spending one slot per call;
- a stock sub-gate (`stock_rate_per_min`, at most the documented 100/min) that
  `stock` calls spend IN ADDITION to the global one;
- a replenishment sub-gate (`replenishment_rate_per_min`, default 30, at most 100/min) that
  `replenishment` calls spend IN ADDITION to the global one;
- per endpoint family (ML limits per Client ID and per endpoint), a 429 cooldown
  honoring `Retry-After` (seconds or HTTP date) or, without a usable header,
  exponential backoff with jitter capped at 60 s; and AIMD: each 429 halves that
  family's rate for ten minutes, then it is restored in steps. A 429 never slows
  the other families; all of them keep sharing the global gate.

Each gate gives one slot per interval (a one-token bucket), so the budget is
never exceeded, not even by a start-up burst; a call fires when its caller wakes
up, so a late wake-up can only bring it closer to the next slot by that delay. A
caller first waits out its family's own constraints holding nothing (so a
throttled family never makes the others wait), then is given its global slot
before it sleeps, so callers asking at once are spread over the budget instead
of waking up together. A slot given before a 429 of its family is forfeited: the
caller waits out the cooldown and takes a new one.

`acquire` never sleeps past the caller's deadline: when the wait would cross it
the call is refused (`DEADLINE`) and nothing is consumed (a forfeited slot
aside). Time comes from an injectable clock so the budget is testable without
sleeping.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Protocol

GRANTED = "granted"
DEADLINE = "deadline"

STOCK_FAMILY = "stock"
MAX_STOCK_PER_MIN = 100  # documented ML limit for /user-products/{id}/stock
REPLENISHMENT_FAMILY = "replenishment"
DEFAULT_REPLENISHMENT_PER_MIN = 30  # a sweep of weekly data: slow on purpose, it must never crowd out live work
MAX_REPLENISHMENT_PER_MIN = 100

BACKOFF_CAP_SECONDS = 60.0
# A `Retry-After` beyond this is clamped: ML retries notifications for about an hour,
# and an unbounded value would park the job (and its claims) indefinitely.
MAX_COOLDOWN_SECONDS = 3600.0
AIMD_PENALTY_SECONDS = 600.0
AIMD_RECOVERY_STEP_SECONDS = 60.0
AIMD_RECOVERY_STEP = 0.125
AIMD_FLOOR = 1.0 / 16


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def now(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class _Gate:
    """Admits one call per `interval`; `next_at` is the earliest next admission."""

    next_at: float = float("-inf")


@dataclass
class _Family:
    """One endpoint family's 429 state: its cooldown, backoff exponent and AIMD penalty, and the gate that applies
    the penalty (only spent while the family is penalized)."""

    gate: _Gate = field(default_factory=_Gate)
    cooldown_until: float = float("-inf")
    consecutive_429: int = 0
    penalized: float = 1.0
    penalty_until: float = float("-inf")


def parse_retry_after(header: Optional[str], now: datetime) -> Optional[float]:
    """Seconds to wait from a `Retry-After` value (delta-seconds or HTTP date), or None if unusable."""
    if header is None:
        return None
    value = header.strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - now).total_seconds())


class Pacer:
    def __init__(
        self,
        *,
        rate_per_sec: float = 2.0,
        stock_rate_per_min: int = 60,
        replenishment_rate_per_min: int = DEFAULT_REPLENISHMENT_PER_MIN,
        clock: Optional[Clock] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._clock: Clock = clock or SystemClock()
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._global = _Gate()
        self._stock = _Gate()
        self._replenishment = _Gate()
        self._families: dict[str, _Family] = {}
        self._replenishment_rate_per_min = DEFAULT_REPLENISHMENT_PER_MIN
        self.configure(
            rate_per_sec=rate_per_sec,
            stock_rate_per_min=stock_rate_per_min,
            replenishment_rate_per_min=replenishment_rate_per_min,
        )

    def configure(
        self, *, rate_per_sec: float, stock_rate_per_min: int, replenishment_rate_per_min: Optional[int] = None
    ) -> None:
        """Apply (possibly runtime-changed) budgets; takes effect on the next call. A caller that does not know
        the replenishment budget (`None`) leaves the one already set."""
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        if not 1 <= stock_rate_per_min <= MAX_STOCK_PER_MIN:
            raise ValueError(f"stock_rate_per_min must be between 1 and {MAX_STOCK_PER_MIN}")
        if replenishment_rate_per_min is not None and not 1 <= replenishment_rate_per_min <= MAX_REPLENISHMENT_PER_MIN:
            raise ValueError(f"replenishment_rate_per_min must be between 1 and {MAX_REPLENISHMENT_PER_MIN}")
        with self._lock:
            self._rate_per_sec = float(rate_per_sec)
            self._stock_rate_per_min = int(stock_rate_per_min)
            if replenishment_rate_per_min is not None:
                self._replenishment_rate_per_min = int(replenishment_rate_per_min)

    def _family(self, family: str) -> _Family:
        return self._families.setdefault(family, _Family())

    # --- AIMD -------------------------------------------------------------------------

    @staticmethod
    def _factor(state: _Family, now: float) -> float:
        if now < state.penalty_until:
            return state.penalized
        steps = int((now - state.penalty_until) // AIMD_RECOVERY_STEP_SECONDS) if state.penalized < 1.0 else 0
        return min(1.0, state.penalized + steps * AIMD_RECOVERY_STEP)

    def effective_rate(self, family: str) -> float:
        """The rate `family` may call at now: the global one, halved by each recent 429 of the family."""
        with self._lock:
            return self._rate_per_sec * self._factor(self._family(family), self._clock.monotonic())

    # --- 429 handling -----------------------------------------------------------------

    def on_rate_limited(self, family: str, retry_after: Optional[str]) -> float:
        """Register a 429 of `family`: start its cooldown and halve its rate. Returns the cooldown in seconds."""
        with self._lock:
            state = self._family(family)
            now = self._clock.monotonic()
            state.consecutive_429 += 1
            delay = parse_retry_after(retry_after, self._clock.now())
            if delay is None:
                cap = min(2.0**state.consecutive_429, BACKOFF_CAP_SECONDS)
                delay = cap * self._rng.uniform(0.5, 1.0)
            delay = min(delay, MAX_COOLDOWN_SECONDS)
            state.cooldown_until = max(state.cooldown_until, now + delay)
            state.penalized = max(self._factor(state, now) / 2, AIMD_FLOOR)
            state.penalty_until = now + AIMD_PENALTY_SECONDS
            return delay

    def on_success(self, family: str) -> None:
        with self._lock:
            self._family(family).consecutive_429 = 0

    def cooldown_remaining(self, family: str) -> float:
        with self._lock:
            return max(0.0, self._family(family).cooldown_until - self._clock.monotonic())

    # --- admission --------------------------------------------------------------------

    def acquire(self, family: str, deadline: Optional[datetime] = None) -> str:
        """Wait for a slot and spend it. Returns `DEADLINE` (nothing spent, never sleeping past `deadline`) when
        the wait would cross `deadline`: before the family's own wait, or once it is over, before the global slot.

        Two steps: first the family's own wait (its cooldown, its penalty, the stock or replenishment budget),
        holding nothing, so a throttled family never makes the others wait; then, once the family may call, a
        global slot, given under the lock before sleeping toward it."""
        if deadline is not None and deadline.tzinfo is None:
            raise ValueError("deadline must be timezone-aware")
        while True:
            with self._lock:
                now = self._clock.monotonic()
                family_ready = self._family_ready(family)
                reserved = family_ready <= now
                wait = max(now, self._global.next_at) - now if reserved else family_ready - now
                if deadline is not None and wait > (deadline - self._clock.now()).total_seconds():
                    return DEADLINE
                if reserved:
                    self._spend(family, now + wait)
            if wait > 0:
                self._clock.sleep(wait)
            if not reserved:
                continue  # the family may call now: take a global slot
            with self._lock:
                # A 429 of the family may have landed while this caller slept toward its slot.
                if self._family(family).cooldown_until <= self._clock.monotonic():
                    return GRANTED

    def _gates(self, family: str) -> list[_Gate]:
        """The family's own gates: its penalty gate, and the stock or replenishment budget it also spends."""
        gates = [self._family(family).gate]
        if family == STOCK_FAMILY:
            gates.append(self._stock)
        if family == REPLENISHMENT_FAMILY:
            gates.append(self._replenishment)
        return gates

    def _family_ready(self, family: str) -> float:
        """Under the lock: when the family's own constraints let it call (its cooldown and its gates)."""
        return max([self._family(family).cooldown_until, *(gate.next_at for gate in self._gates(family))])

    def _spend(self, family: str, slot: float) -> None:
        """Under the lock: give the caller the global slot `slot` and spend the family's gates from it."""
        state = self._family(family)
        factor = self._factor(state, slot)
        self._global.next_at = slot + 1.0 / self._rate_per_sec
        if factor < 1.0:  # at full rate the global gate already spaces the family's calls
            state.gate.next_at = slot + 1.0 / (self._rate_per_sec * factor)
        if family == STOCK_FAMILY:
            self._stock.next_at = slot + 60.0 / (self._stock_rate_per_min * factor)
        if family == REPLENISHMENT_FAMILY:
            self._replenishment.next_at = slot + 60.0 / (self._replenishment_rate_per_min * factor)
