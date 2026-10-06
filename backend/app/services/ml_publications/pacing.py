"""One in-process ML budget for every call the store makes (design D11).

The worker runtime is single-threaded, so a per-process pacer is an exact
budget. It combines:

- a global gate (`rate_per_sec`, default 2/s) spending one slot per call;
- a stock sub-gate (`stock_rate_per_min`, at most the documented 100/min) that
  `stock` calls spend IN ADDITION to the global one;
- a 429 cooldown honoring `Retry-After` (seconds or HTTP date) or, without a
  usable header, exponential backoff with jitter capped at 60 s;
- AIMD: each 429 halves the effective rate for ten minutes, then the rate is
  restored in steps.

Each gate admits one call per interval (a one-token bucket), so in any window
of one interval there is at most one call: the observed rate never exceeds the
budget, not even by a start-up burst.

`acquire` never sleeps past the caller's deadline: when the wait would cross it
the call is refused (`DEADLINE`) and nothing is consumed. Time comes from an
injectable clock so the budget is testable without sleeping.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Protocol

GRANTED = "granted"
DEADLINE = "deadline"

STOCK_FAMILY = "stock"
MAX_STOCK_PER_MIN = 100  # documented ML limit for /user-products/{id}/stock

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
        clock: Optional[Clock] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._clock: Clock = clock or SystemClock()
        self._rng = rng or random.Random()
        self._global = _Gate()
        self._stock = _Gate()
        self._cooldown_until = float("-inf")
        self._consecutive_429 = 0
        self._penalized = 1.0
        self._penalty_until = float("-inf")
        self.configure(rate_per_sec=rate_per_sec, stock_rate_per_min=stock_rate_per_min)

    def configure(self, *, rate_per_sec: float, stock_rate_per_min: int) -> None:
        """Apply (possibly runtime-changed) budgets; takes effect on the next call."""
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        if not 1 <= stock_rate_per_min <= MAX_STOCK_PER_MIN:
            raise ValueError(f"stock_rate_per_min must be between 1 and {MAX_STOCK_PER_MIN}")
        self._rate_per_sec = float(rate_per_sec)
        self._stock_rate_per_min = int(stock_rate_per_min)

    # --- AIMD -------------------------------------------------------------------------

    def _factor(self, now: float) -> float:
        if now < self._penalty_until:
            return self._penalized
        steps = int((now - self._penalty_until) // AIMD_RECOVERY_STEP_SECONDS) if self._penalized < 1.0 else 0
        return min(1.0, self._penalized + steps * AIMD_RECOVERY_STEP)

    def effective_rate(self) -> float:
        return self._rate_per_sec * self._factor(self._clock.monotonic())

    # --- 429 handling -----------------------------------------------------------------

    def on_rate_limited(self, retry_after: Optional[str]) -> float:
        """Register a 429: start a cooldown and halve the effective rate. Returns the cooldown in seconds."""
        now = self._clock.monotonic()
        self._consecutive_429 += 1
        delay = parse_retry_after(retry_after, self._clock.now())
        if delay is None:
            cap = min(2.0**self._consecutive_429, BACKOFF_CAP_SECONDS)
            delay = cap * self._rng.uniform(0.5, 1.0)
        delay = min(delay, MAX_COOLDOWN_SECONDS)
        self._cooldown_until = max(self._cooldown_until, now + delay)
        self._penalized = max(self._factor(now) / 2, AIMD_FLOOR)
        self._penalty_until = now + AIMD_PENALTY_SECONDS
        return delay

    def on_success(self) -> None:
        self._consecutive_429 = 0

    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - self._clock.monotonic())

    # --- admission --------------------------------------------------------------------

    def acquire(self, family: str, deadline: Optional[datetime] = None) -> str:
        """Wait for a slot and spend it. Returns `DEADLINE` (nothing spent, nothing slept) when
        the wait would cross `deadline`."""
        now = self._clock.monotonic()
        is_stock = family == STOCK_FAMILY
        ready_at = max(self._cooldown_until, self._global.next_at)
        if is_stock:
            ready_at = max(ready_at, self._stock.next_at)
        wait = max(0.0, ready_at - now)
        if deadline is not None and wait > (deadline - self._clock.now()).total_seconds():
            return DEADLINE
        if wait > 0:
            self._clock.sleep(wait)
        granted_at = self._clock.monotonic()
        factor = self._factor(granted_at)
        self._global.next_at = granted_at + 1.0 / (self._rate_per_sec * factor)
        if is_stock:
            self._stock.next_at = granted_at + 60.0 / (self._stock_rate_per_min * factor)
        return GRANTED
