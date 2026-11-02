"""ml-ads-cupones-display T3a -- `ml_orders.discounts`: gate, per-minute cap and the run summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.ml_order_discounts import ingestion
from app.workers.context import WorkerContext
from app.workers.handlers import ml_order_discounts as module

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def handler(clock: Clock) -> module.OrderDiscountsHandler:
    return module.OrderDiscountsHandler(
        client_factory=lambda pacer: object(), session_factory=lambda: None, now=lambda: NOW, monotonic=clock
    )


def ctx() -> WorkerContext:
    return WorkerContext(deadline=NOW + timedelta(seconds=30))


def test_disabled_without_ml_ads(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", False)
    called = []
    monkeypatch.setattr(ingestion, "run", lambda *a, **k: called.append(1))
    result = handler(Clock()).run(ctx())
    assert result.detail == {"disabled": True} and called == []


def test_spends_at_most_thirty_calls_per_minute_and_returns_the_summary(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    seen = []

    def fake_run(session_factory, client, *, now, deadline, max_calls):
        seen.append((max_calls, deadline))
        return ingestion.RunResult(calls=max_calls, pending_left=7)

    monkeypatch.setattr(ingestion, "run", fake_run)
    clock = Clock()
    h = handler(clock)
    first = h.run(ctx())
    assert seen == [(30, NOW + timedelta(seconds=20))]
    assert first.detail["calls"] == 30 and first.detail["pending_left"] == 7
    assert h.run(ctx()).detail == {"calls": 0, "stopped": "rate_cap"}
    clock.value += 61
    h.run(ctx())
    assert seen[-1][0] == 30


def test_blocked_is_reported_as_an_error(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    monkeypatch.setattr(ingestion, "run", lambda *a, **k: ingestion.RunResult(stopped="blocked"))
    result = handler(Clock()).run(ctx())
    assert result.success and result.error == "missing or rejected ML credentials"


def test_a_failing_run_is_reported_not_raised(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ingestion, "run", boom)
    h = handler(Clock())
    result = h.run(ctx())
    assert not result.success and result.error == "RuntimeError: db down"
    # The calls of a failed run are unknown: the whole minute's budget is taken as spent.
    assert h.run(ctx()).detail == {"calls": 0, "stopped": "rate_cap"}
