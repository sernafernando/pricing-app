"""`bundle.plan`: what a queue entry asks for, against the `bundle_resources` gate (design D12). Pure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.ml_publications import bundle
from app.services.ml_publications.resources import REFRESH_RESOURCES, RESOURCES

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)


class TestFetchers:
    def test_the_fetchers_are_description_prices_and_sale_price(self) -> None:
        assert set(bundle.FETCHERS) == {"description", "prices", "sale_price"}

    def test_every_fetcher_has_a_registered_resource_and_a_canonical_name(self) -> None:
        for name in bundle.FETCHERS:
            assert name in RESOURCES and name in REFRESH_RESOURCES

    def test_paths_follow_the_captured_endpoints(self) -> None:
        paths = {name: f.request("MLA1") for name, f in bundle.FETCHERS.items()}
        assert paths == {
            "description": ("/items/MLA1/description", None),
            "prices": ("/items/MLA1/prices", None),
            "sale_price": ("/items/MLA1/sale_price", {"context": "channel_marketplace"}),
        }


class TestPlan:
    def test_the_default_gate_asks_for_the_core_only(self) -> None:
        plan = bundle.plan(("bundle",), ["core"])
        assert (plan.needs_core, dict(plan.wanted), plan.dropped) == (True, {}, frozenset())

    def test_a_bundle_asks_for_every_enabled_fetchable_resource_implicitly(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "description", "prices"])
        assert plan.needs_core is True
        assert dict(plan.wanted) == {"description": False, "prices": False}  # False = not explicit

    def test_an_enabled_resource_without_a_fetcher_is_dropped_not_wanted(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "prices", "promotions"])
        assert dict(plan.wanted) == {"prices": False} and plan.dropped == {"promotions"}

    def test_an_explicit_named_resource_is_wanted_explicitly_and_needs_no_core(self) -> None:
        plan = bundle.plan(("prices", "sale_price"), ["core", "prices", "sale_price"])
        assert plan.needs_core is False
        assert dict(plan.wanted) == {"prices": True, "sale_price": True}

    def test_an_explicit_resource_that_is_not_enabled_is_dropped(self) -> None:
        plan = bundle.plan(("description",), ["core"])
        assert plan.needs_core is False and dict(plan.wanted) == {} and plan.dropped == {"description"}

    def test_explicit_wins_over_the_implicit_bundle_for_the_same_name(self) -> None:
        plan = bundle.plan(("bundle", "description"), ["core", "description"])
        assert dict(plan.wanted) == {"description": True}

    def test_core_and_bundle_both_need_the_core(self) -> None:
        assert bundle.plan(("core",), []).needs_core is True
        assert bundle.plan(("bundle",), []).needs_core is True

    @pytest.mark.parametrize("name", [n for n in REFRESH_RESOURCES if n not in ("core", "bundle")])
    def test_every_other_canonical_name_is_dropped_when_nothing_is_enabled(self, name) -> None:
        plan = bundle.plan((name,), [])
        assert plan.needs_core is False and dict(plan.wanted) == {} and plan.dropped == {name}


class TestMinAge:
    def test_configured_ages_are_read_and_prices_default_to_zero(self) -> None:
        configured = {"description": 21600}
        assert bundle.min_age_seconds("description", configured) == 21600
        assert bundle.min_age_seconds("prices", configured) == 0
        assert bundle.min_age_seconds("sale_price", configured) == 0

    def test_an_explicit_request_is_always_due(self) -> None:
        assert bundle.is_due(explicit=True, min_age=21600, last_checked_at=NOW, now=NOW) is True

    def test_a_never_fetched_resource_is_due(self) -> None:
        assert bundle.is_due(explicit=False, min_age=21600, last_checked_at=None, now=NOW) is True

    def test_an_implicit_request_waits_for_the_minimum_age(self) -> None:
        fresh = NOW - timedelta(hours=5, minutes=59)
        stale = NOW - timedelta(hours=6)
        assert bundle.is_due(explicit=False, min_age=21600, last_checked_at=fresh, now=NOW) is False
        assert bundle.is_due(explicit=False, min_age=21600, last_checked_at=stale, now=NOW) is True

    def test_a_zero_minimum_age_is_always_due(self) -> None:
        assert bundle.is_due(explicit=False, min_age=0, last_checked_at=NOW, now=NOW) is True
