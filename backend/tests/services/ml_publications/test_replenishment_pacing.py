"""Pacer sub-gate of the replenishment endpoint (P4b): `replenishment_rate_per_min`, default 30, at most 100.

Same fake clock as `test_pacing`: no test sleeps for real. A 429 on the endpoint goes through the existing
`MlHttpClient._finish` -> `Pacer.on_rate_limited` path (cooldown and AIMD for every ML call).
"""

from __future__ import annotations

import random

import httpx
import pytest

from app.core.config import Settings, settings
from app.services.ml_publications import settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import GRANTED, MAX_REPLENISHMENT_PER_MIN, Pacer
from tests.services.ml_publications.test_ml_http import Ticking, Tokens
from tests.services.ml_publications.test_pacing import FakeClock, grant_times, make


class TestSubBudget:
    def test_calls_stay_at_or_below_the_configured_per_minute(self) -> None:
        clock = FakeClock()
        pacer = make(clock, rate_per_sec=20.0, replenishment_rate_per_min=30)
        times = grant_times(pacer, clock, ["replenishment"] * 80)
        assert max(sum(1 for u in times if t <= u < t + 60.0) for t in times) <= 30
        assert times[1] - times[0] == pytest.approx(2.0)

    def test_the_default_is_30_a_minute(self) -> None:
        clock = FakeClock()
        pacer = make(clock, rate_per_sec=20.0)
        times = grant_times(pacer, clock, ["replenishment"] * 3)
        assert times[1] - times[0] == pytest.approx(2.0)

    def test_it_does_not_slow_other_endpoints_nor_the_stock_gate(self) -> None:
        clock = FakeClock()
        pacer = make(clock, rate_per_sec=2.0, stock_rate_per_min=60, replenishment_rate_per_min=30)
        others = grant_times(pacer, clock, ["items_bulk"] * 10)
        assert others[-1] - others[0] == pytest.approx(9 * 0.5)
        stock = grant_times(pacer, clock, ["stock"] * 3)
        assert stock[1] - stock[0] == pytest.approx(1.0)

    def test_its_calls_also_spend_the_global_budget(self) -> None:
        clock = FakeClock()
        pacer = make(clock, rate_per_sec=2.0, replenishment_rate_per_min=100)
        times = grant_times(pacer, clock, ["replenishment", "items_bulk"] * 30)
        assert all(times[i + 2] - times[i] >= 1.0 - 1e-9 for i in range(len(times) - 2))
        own = times[0::2]
        assert all(b - a >= 0.6 - 1e-9 for a, b in zip(own, own[1:]))

    def test_a_budget_above_100_a_minute_or_below_1_is_rejected(self) -> None:
        assert MAX_REPLENISHMENT_PER_MIN == 100
        for bad in (0, 101):
            with pytest.raises(ValueError, match="replenishment_rate_per_min"):
                make(FakeClock(), replenishment_rate_per_min=bad)

    def test_configure_applies_a_new_budget_and_keeps_it_when_not_given(self) -> None:
        clock = FakeClock()
        pacer = make(clock, rate_per_sec=20.0, replenishment_rate_per_min=30)
        grant_times(pacer, clock, ["replenishment"])
        pacer.configure(rate_per_sec=20.0, stock_rate_per_min=60, replenishment_rate_per_min=60)
        times = grant_times(pacer, clock, ["replenishment"] * 2)
        assert times[1] - times[0] == pytest.approx(1.0)
        pacer.configure(rate_per_sec=20.0, stock_rate_per_min=60)  # callers that do not know it keep it
        times = grant_times(pacer, clock, ["replenishment"] * 2)
        assert times[1] - times[0] == pytest.approx(1.0)

    def test_the_deadline_refuses_a_call_the_sub_gate_would_delay_past_it(self) -> None:
        from datetime import timedelta

        clock = FakeClock()
        pacer = make(clock, rate_per_sec=20.0, replenishment_rate_per_min=30)
        assert pacer.acquire("replenishment") == GRANTED
        assert pacer.acquire("replenishment", clock.now() + timedelta(seconds=1)) == "deadline"


class TestRateLimited:
    def test_a_429_on_the_endpoint_starts_the_shared_cooldown(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_USER_ID", "1")
        monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
        clock = FakeClock()
        client = MlHttpClient(
            pacer=Pacer(clock=clock, rng=random.Random(1)),
            transport=httpx.MockTransport(lambda request: httpx.Response(429, headers={"retry-after": "30"})),
            token_loader=Tokens(),
            now=Ticking(),
        )
        response = client.get("replenishment", "/marketplace/fbm/user-products/MLAU1/replenishment", {"country": "AR"})
        assert response.status == 429
        assert client.pacer.cooldown_remaining() == pytest.approx(30.0)
        assert client.pacer.effective_rate() < 2.0  # AIMD halved the shared rate


class TestSetting:
    def test_it_is_an_allow_listed_setting_between_1_and_100(self) -> None:
        definition = settings_store.SETTING_DEFS["replenishment_rate_per_min"]
        assert definition.env_attr == "ML_PUB_REPLENISHMENT_RATE_PER_MIN"
        assert [definition.valid(v) for v in (1, 30, 100, 0, 101, True, "30", 2.5)] == [
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
        ]

    def test_the_env_default_is_30_and_bounded(self) -> None:
        assert Settings.model_fields["ML_PUB_REPLENISHMENT_RATE_PER_MIN"].default == 30
        for bad in (0, 101):
            with pytest.raises(ValueError):
                Settings(ML_PUB_REPLENISHMENT_RATE_PER_MIN=bad)
