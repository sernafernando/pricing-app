"""ml-ads-cupones-display T3a -- `ml_orders.discounts`: gate, run size and the run summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.ml_order_discounts import ingestion
from app.workers.context import WorkerContext
from app.workers.handlers import ml_order_discounts as module

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def handler() -> module.OrderDiscountsHandler:
    return module.OrderDiscountsHandler(
        client_factory=lambda pacer: object(), session_factory=lambda: None, now=lambda: NOW
    )


def ctx() -> WorkerContext:
    return WorkerContext(deadline=NOW + timedelta(seconds=module.discounts.deadline_seconds))


def test_disabled_without_ml_ads(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", False)
    called = []
    monkeypatch.setattr(ingestion, "run", lambda *a, **k: called.append(1))
    result = handler().run(ctx())
    assert result.detail == {"disabled": True} and called == []


def test_asks_for_at_most_per_run_orders_within_the_run_budget_and_returns_the_summary(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    seen = []

    def fake_run(session_factory, client, *, now, deadline, max_calls, should_stop):
        seen.append((max_calls, deadline, should_stop()))
        return ingestion.RunResult(calls=max_calls, pending_left=7)

    monkeypatch.setattr(ingestion, "run", fake_run)
    result = handler().run(ctx())
    assert seen == [(module.PER_RUN, NOW + module.RUN_BUDGET, False)]
    assert result.success and result.detail["calls"] == module.PER_RUN and result.detail["pending_left"] == 7


def test_blocked_is_reported_as_an_error(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    monkeypatch.setattr(ingestion, "run", lambda *a, **k: ingestion.RunResult(stopped="blocked"))
    result = handler().run(ctx())
    assert result.success and result.error == "missing or rejected ML credentials"


def test_a_failing_run_is_reported_not_raised_every_time(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ingestion, "run", boom)
    h = handler()
    for _ in range(2):
        result = h.run(ctx())
        assert not result.success and result.error == "RuntimeError: db down"


def test_an_idle_run_spaces_the_next_query_by_a_minute(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    calls = []
    at = [NOW]

    def fake_run(*args, **kwargs):
        calls.append(at[0])
        return ingestion.RunResult(calls=0, pending_left=0)  # an empty queue

    monkeypatch.setattr(ingestion, "run", fake_run)
    h = module.OrderDiscountsHandler(
        client_factory=lambda pacer: object(), session_factory=lambda: None, now=lambda: at[0]
    )
    first = h.run(ctx())
    at[0] = NOW + timedelta(seconds=30)
    second = h.run(ctx())
    assert calls == [NOW] and second.success
    assert second.detail == {**first.detail, "idle_until": (NOW + module.IDLE_PAUSE).isoformat()}
    at[0] = NOW + module.IDLE_PAUSE
    h.run(ctx())
    assert calls == [NOW, NOW + module.IDLE_PAUSE]


def test_a_back_off_spaces_the_next_query_until_it_ends_or_a_minute(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    calls = []
    at = [NOW]
    ends = NOW + timedelta(seconds=20)

    def fake_run(*args, **kwargs):
        calls.append(at[0])
        return ingestion.RunResult(stopped=ingestion.BACKOFF, backoff_until=ends, pending_left=3)

    monkeypatch.setattr(ingestion, "run", fake_run)
    h = module.OrderDiscountsHandler(
        client_factory=lambda pacer: object(), session_factory=lambda: None, now=lambda: at[0]
    )
    h.run(ctx())
    at[0] = NOW + timedelta(seconds=19)
    h.run(ctx())
    at[0] = ends
    h.run(ctx())
    assert calls == [NOW, ends]


def test_a_run_with_work_does_not_pause(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    calls = []
    monkeypatch.setattr(
        ingestion, "run", lambda *a, **k: calls.append(1) or ingestion.RunResult(calls=3, pending_left=9)
    )
    h = handler()
    h.run(ctx())
    h.run(ctx())
    assert calls == [1, 1]


def test_blocked_or_transport_waits_a_minute_before_calling_again(monkeypatch) -> None:
    monkeypatch.setattr(module.settings, "ML_ADS_ENABLED", True)
    for stopped in ("blocked", "transport"):
        calls = []
        at = [NOW]
        monkeypatch.setattr(
            ingestion, "run", lambda *a, **k: calls.append(at[0]) or ingestion.RunResult(calls=1, stopped=stopped)
        )
        h = module.OrderDiscountsHandler(
            client_factory=lambda pacer: object(), session_factory=lambda: None, now=lambda: at[0]
        )
        first = h.run(ctx())
        at[0] = NOW + timedelta(seconds=30)
        second = h.run(ctx())
        assert calls == [NOW], stopped
        assert second.error == first.error and second.error  # the pause keeps reporting why
        at[0] = NOW + module.IDLE_PAUSE
        h.run(ctx())
        assert calls == [NOW, NOW + module.IDLE_PAUSE], stopped
