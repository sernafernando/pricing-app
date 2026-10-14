"""`ml_publications.promo_refresh`: drains the reactivation queue through the proxy refresh call.

Postgres only. Items are the store's captured bodies applied through `apply_fetch`; the ml-webhook client is
the only thing mocked. Due times are compared with the real clock (the claim compares against `now`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from sqlalchemy import text

from app.services import promo_refresh_queue as queue
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.settings_store import set_setting
from app.services.ml_webhook_client import RefreshOutcome, ml_webhook_client
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers.ml_promo_refresh import PromoRefreshHandler
from tests.services.ml_publications.conftest import item_with_variations, sample_item
from tests.services.ml_publications.test_store_apply_fetch import ACTIVE, apply

pytestmark = pytest.mark.postgres

CLOSED = "MLA1207279308"
PAUSED = "MLA862580589"  # captured paused item
OTHER_ACTIVE = "MLA882393030"  # captured active item


def now() -> datetime:
    return datetime.now(timezone.utc)


def ctx() -> WorkerContext:
    return WorkerContext(deadline=now() + timedelta(seconds=30), worker_name="test")


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def env(mlpub_pg):
    apply(sample_item(ACTIVE), ACTIVE, minutes=1)
    apply(sample_item(PAUSED), PAUSED, minutes=1)
    apply(sample_item(OTHER_ACTIVE), OTHER_ACTIVE, minutes=1)
    apply(item_with_variations(), CLOSED, minutes=1)
    set_setting("promo_refresh.enabled", True, "test")
    return mlpub_pg


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def handler(clock) -> PromoRefreshHandler:
    return PromoRefreshHandler(pacer=Pacer(rate_per_sec=20), monotonic=clock)


@pytest.fixture
def proxy():
    with mock.patch.object(
        ml_webhook_client, "refresh_item_promotions", new=mock.AsyncMock(return_value=RefreshOutcome(ok=True))
    ) as call:
        yield call


def put(engine, mla: str, *, due_in: float = -1, attempts: int = 0) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO promo_refresh_pending (mla, due_at, attempts) VALUES (:m, :d, :a)"),
            {"m": mla, "d": now() + timedelta(seconds=due_in), "a": attempts},
        )


def rows(engine) -> dict:
    with engine.connect() as conn:
        return {r.mla: r for r in conn.execute(text("SELECT mla, due_at, attempts FROM promo_refresh_pending"))}


class TestRegistration:
    def test_it_is_in_the_ml_worker_registry_and_not_in_the_sales_one(self) -> None:
        names = [h.name for h in registry.ML_PUBLICATIONS_REGISTRY]
        assert "ml_publications.promo_refresh" in names
        assert "ml_publications.promo_refresh" not in [h.name for h in registry.REGISTRY]


class TestDrain:
    def test_a_due_active_row_is_refreshed_once_and_removed(self, env, handler, proxy) -> None:
        put(env, ACTIVE)

        result = handler.run(ctx())

        proxy.assert_awaited_once_with(ACTIVE)
        assert result.success and result.detail["refreshed"] == 1
        assert rows(env) == {}

    def test_a_row_not_due_yet_is_left_alone(self, env, handler, proxy) -> None:
        put(env, ACTIVE, due_in=600)

        handler.run(ctx())

        proxy.assert_not_called()
        assert list(rows(env)) == [ACTIVE]

    @pytest.mark.parametrize("mla", [PAUSED, CLOSED, "MLA999999999999"])
    def test_an_item_that_is_not_active_is_dropped_without_a_call(self, env, handler, proxy, mla) -> None:
        """paused, closed (both captured) and one the store never saw."""
        put(env, mla)

        result = handler.run(ctx())

        proxy.assert_not_called()
        assert result.detail["dropped"] == 1 and rows(env) == {}

    def test_a_gone_item_is_dropped_without_a_call(self, env, handler, proxy) -> None:
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_items SET gone_at = now() WHERE item_id = :i"), {"i": ACTIVE})
        put(env, ACTIVE)

        handler.run(ctx())

        proxy.assert_not_called()
        assert rows(env) == {}


class TestFailure:
    def test_a_failure_backs_off_and_charges_one_attempt(self, env, handler, proxy) -> None:
        proxy.return_value = RefreshOutcome(ok=False, motivo="502", reintentable=True)
        put(env, ACTIVE)

        result = handler.run(ctx())

        row = rows(env)[ACTIVE]
        assert result.detail["failed"] == 1 and row.attempts == 1
        assert row.due_at > now() + timedelta(seconds=queue.backoff_seconds(1) - 5)

    def test_an_exception_from_the_client_is_a_failure_not_a_crash(self, env, handler, proxy) -> None:
        proxy.side_effect = RuntimeError("boom")
        put(env, ACTIVE)

        result = handler.run(ctx())

        assert result.success and rows(env)[ACTIVE].attempts == 1

    def test_backoff_grows_and_is_capped(self) -> None:
        assert [queue.backoff_seconds(n) for n in (1, 2, 3)] == [60, 120, 240]
        assert queue.backoff_seconds(50) == queue.BACKOFF_CAP_SECONDS

    def test_the_last_allowed_attempt_quarantines_the_row(self, env, handler, proxy) -> None:
        proxy.return_value = RefreshOutcome(ok=False, motivo="502", reintentable=True)
        put(env, ACTIVE, attempts=queue.MAX_ATTEMPTS - 1)

        result = handler.run(ctx())

        assert result.detail["quarantined"] == 1 and rows(env) == {}

    def test_a_failure_that_retrying_cannot_fix_is_dropped_at_once(self, env, handler, proxy) -> None:
        proxy.return_value = RefreshOutcome(ok=False, motivo="closed", reintentable=False)
        put(env, ACTIVE)

        handler.run(ctx())

        proxy.assert_awaited_once()
        assert rows(env) == {}


class TestGates:
    def test_flag_off_makes_no_call_and_touches_nothing(self, env, handler, proxy) -> None:
        set_setting("promo_refresh.enabled", False, "test")
        put(env, ACTIVE)

        result = handler.run(ctx())

        proxy.assert_not_called()
        assert result.detail == {"disabled": True} and list(rows(env)) == [ACTIVE]

    def test_the_flag_defaults_off_without_any_setting_row(self, mlpub_pg, handler, proxy) -> None:
        assert handler.run(ctx()).detail == {"disabled": True}
        proxy.assert_not_called()

    def test_the_per_minute_cap_limits_calls_then_resumes_after_the_window(self, env, handler, proxy, clock) -> None:
        set_setting("promo_refresh.rate_per_min", 1, "test")
        put(env, ACTIVE, due_in=-10)
        put(env, OTHER_ACTIVE, due_in=-5)

        first = handler.run(ctx())
        assert proxy.await_count == 1 and first.detail["stopped"] == "rate_cap" and list(rows(env)) == [OTHER_ACTIVE]

        handler.run(ctx())  # same minute: still capped
        assert proxy.await_count == 1

        clock.at += 61
        handler.run(ctx())
        assert proxy.await_count == 2 and rows(env) == {}
