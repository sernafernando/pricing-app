"""`bundle.plan`: what a queue entry asks for, against the `bundle_resources` gate (design D12). Pure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.ml_publications import bundle
from app.services.ml_publications.resources import REFRESH_RESOURCES, RESOURCES

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)


class TestFetchers:
    def test_the_fetchers_are_the_item_sub_resources_and_the_user_product_family(self) -> None:
        assert set(bundle.FETCHERS) == {
            "description",
            "prices",
            "sale_price",
            "promotions",
            "user_product",
            "stock",
            "family",
            "competition",
            "moderation",
            "performance",
            "visits",
            "replenishment",
        }

    def test_every_fetcher_has_a_registered_resource_and_a_canonical_name(self) -> None:
        for name in bundle.FETCHERS:
            assert name in RESOURCES and name in REFRESH_RESOURCES

    def test_paths_follow_the_captured_endpoints(self) -> None:
        paths = {name: f.request("MLA1") for name, f in bundle.FETCHERS.items()}
        assert paths == {
            "description": ("/items/MLA1/description", None),
            "prices": ("/items/MLA1/prices", None),
            "sale_price": ("/items/MLA1/sale_price", {"context": "channel_marketplace"}),
            "promotions": ("/seller-promotions/items/MLA1", {"app_version": "v2"}),
            "user_product": ("/user-products/MLA1", None),
            "stock": ("/user-products/MLA1/stock", None),
            "family": ("/sites/MLA/user-products-families/MLA1", None),
            "competition": ("/items/MLA1/price_to_win", {"version": "v2"}),
            "moderation": ("/moderations/last_moderation/MLA1-ITM", None),
            "performance": ("/item/MLA1/performance", None),
            "visits": ("/items/MLA1/visits/time_window", {"last": "30", "unit": "day"}),
            "replenishment": ("/marketplace/fbm/user-products/MLA1/replenishment", {"country": "AR"}),
        }

    def test_each_fetcher_names_the_entity_whose_id_its_path_takes(self) -> None:
        entities = {name: f.entity for name, f in bundle.FETCHERS.items()}
        assert entities == {
            "description": "item",
            "prices": "item",
            "sale_price": "item",
            "promotions": "item",
            "user_product": "user_product",
            "stock": "user_product",
            "family": "family",
            "competition": "item",
            "moderation": "item",
            "performance": "item",
            "visits": "item",
            "replenishment": "user_product",
        }

    def test_only_promotions_needs_a_flag_of_its_own(self) -> None:
        assert bundle.FLAG_GATES == {"promotions": "promotions.enabled"}


class TestSweepOnlyResources:
    def test_performance_and_visits_are_never_part_of_the_bundle(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "prices", "performance", "visits"])
        assert dict(plan.wanted) == {"prices": False}
        assert plan.dropped == {"performance", "visits"}

    def test_a_named_performance_or_visits_entry_needs_them_enabled_and_is_explicit(self) -> None:
        enabled = bundle.plan(("performance", "visits"), ["core", "performance", "visits"])
        assert dict(enabled.wanted) == {"performance": True, "visits": True} and enabled.needs_core is False
        assert bundle.plan(("performance",), ["core"]).dropped == {"performance"}

    def test_the_bundle_plus_a_named_performance_still_fetches_it_explicitly(self) -> None:
        plan = bundle.plan(("bundle", "performance"), ["core", "performance"])
        assert dict(plan.wanted) == {"performance": True} and plan.dropped == frozenset()


def signals(**fields) -> bundle.ItemSignals:
    return bundle.ItemSignals(**{"catalog_listing": False, "status": "active", "sub_status": [], "tags": [], **fields})


class TestApplicability:
    def test_competition_only_for_catalog_listings_even_when_asked_by_name(self) -> None:
        assert bundle.is_applicable("competition", signals(catalog_listing=True), explicit=False) is True
        assert bundle.is_applicable("competition", signals(catalog_listing=False), explicit=False) is False
        assert bundle.is_applicable("competition", signals(catalog_listing=False), explicit=True) is False
        assert bundle.is_applicable("competition", signals(catalog_listing=None), explicit=True) is False

    def test_competition_of_an_item_not_in_the_store_is_not_requested(self) -> None:
        assert bundle.is_applicable("competition", None, explicit=True) is False

    @pytest.mark.parametrize(
        "fields",
        [
            {"status": "under_review"},
            {"tags": ["good_quality_thumbnail", "moderation_penalty"]},
            {"sub_status": ["waiting_for_patch"]},
            {"sub_status": ["forbidden"]},
        ],
    )
    def test_moderation_on_the_bundle_needs_a_moderation_signal(self, fields) -> None:
        assert bundle.is_applicable("moderation", signals(**fields), explicit=False) is True

    @pytest.mark.parametrize(
        "fields",
        [{}, {"status": "paused", "sub_status": ["out_of_stock"]}, {"tags": ["immediate_payment", "cart_eligible"]}],
    )
    def test_moderation_on_the_bundle_is_skipped_without_a_signal(self, fields) -> None:
        assert bundle.is_applicable("moderation", signals(**fields), explicit=False) is False

    def test_a_named_moderation_entry_is_fetched_whatever_the_item_looks_like(self) -> None:
        assert bundle.is_applicable("moderation", signals(), explicit=True) is True
        assert bundle.is_applicable("moderation", None, explicit=True) is True

    @pytest.mark.parametrize("name", ["description", "prices", "sale_price", "promotions", "performance", "visits"])
    def test_every_other_resource_is_always_applicable(self, name) -> None:
        assert bundle.is_applicable(name, signals(), explicit=False) is True
        assert bundle.is_applicable(name, None, explicit=True) is True


class TestPlan:
    def test_the_default_gate_asks_for_the_core_only(self) -> None:
        plan = bundle.plan(("bundle",), ["core"])
        assert (plan.needs_core, dict(plan.wanted), plan.dropped) == (True, {}, frozenset())

    def test_a_bundle_asks_for_every_enabled_fetchable_resource_implicitly(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "description", "prices"])
        assert plan.needs_core is True
        assert dict(plan.wanted) == {"description": False, "prices": False}  # False = not explicit

    def test_an_enabled_resource_without_a_fetcher_is_dropped_not_wanted(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "prices", "visits"])
        assert dict(plan.wanted) == {"prices": False} and plan.dropped == {"visits"}

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

    def test_a_gated_off_resource_is_dropped_from_the_bundle_and_from_a_named_entry(self) -> None:
        enabled = ["core", "prices", "promotions"]
        gated = frozenset({"promotions"})

        bundle_plan = bundle.plan(("bundle",), enabled, gated)
        named_plan = bundle.plan(("promotions",), enabled, gated)

        assert dict(bundle_plan.wanted) == {"prices": False} and bundle_plan.dropped == {"promotions"}
        assert named_plan.needs_core is False and dict(named_plan.wanted) == {} and named_plan.dropped == {"promotions"}

    def test_a_resource_whose_flag_is_on_is_planned_like_any_other(self) -> None:
        enabled = ["core", "prices", "promotions"]

        assert dict(bundle.plan(("bundle",), enabled, frozenset()).wanted) == {"prices": False, "promotions": False}
        assert dict(bundle.plan(("promotions",), enabled).wanted) == {"promotions": True}

    def test_core_and_bundle_both_need_the_core(self) -> None:
        assert bundle.plan(("core",), []).needs_core is True
        assert bundle.plan(("bundle",), []).needs_core is True

    @pytest.mark.parametrize("name", [n for n in REFRESH_RESOURCES if n not in ("core", "bundle")])
    def test_every_other_canonical_name_is_dropped_when_nothing_is_enabled(self, name) -> None:
        plan = bundle.plan((name,), [])
        assert plan.needs_core is False and dict(plan.wanted) == {} and plan.dropped == {name}


class TestPlanByQueueKind:
    """Entries of kind `user_product` / `family` carry no item: they ask only for the resources of their own entity."""

    ENABLED = ["core", "prices", "user_product", "stock", "family"]

    def test_an_item_bundle_asks_for_the_user_product_resources_beside_the_item_ones(self) -> None:
        plan = bundle.plan(("bundle",), self.ENABLED)
        assert plan.needs_core is True
        assert dict(plan.wanted) == {"prices": False, "user_product": False, "stock": False, "family": False}

    def test_a_user_product_bundle_asks_for_its_own_resources_and_never_for_the_core(self) -> None:
        plan = bundle.plan(("bundle",), self.ENABLED, kind="user_product")
        assert plan.needs_core is False
        assert dict(plan.wanted) == {"user_product": False, "stock": False}
        assert plan.dropped == frozenset()  # an item or family resource is not applicable here, not "dropped"

    def test_a_named_stock_entry_of_a_user_product_is_explicit(self) -> None:
        plan = bundle.plan(("stock",), self.ENABLED, kind="user_product")
        assert dict(plan.wanted) == {"stock": True} and plan.dropped == frozenset()

    def test_a_family_entry_asks_for_the_family_only(self) -> None:
        plan = bundle.plan(("family",), self.ENABLED, kind="family")
        assert plan.needs_core is False and dict(plan.wanted) == {"family": True}
        assert dict(bundle.plan(("bundle",), self.ENABLED, kind="family").wanted) == {"family": False}

    @pytest.mark.parametrize("kind, name", [("user_product", "core"), ("user_product", "prices"), ("family", "stock")])
    def test_a_resource_of_another_entity_named_on_the_entry_is_dropped_uncharged(self, kind, name) -> None:
        plan = bundle.plan((name,), self.ENABLED, kind=kind)
        assert plan.needs_core is False and dict(plan.wanted) == {} and plan.dropped == {name}

    def test_the_bundle_of_a_user_product_never_counts_a_resource_that_was_not_meant_for_it(self) -> None:
        """Gated-off promotions and a resource with no fetcher yet belong to items: on a user product or
        family entry they are not applicable, so they are neither wanted nor dropped (no counter noise)."""
        enabled = [*self.ENABLED, "promotions", "visits"]
        for kind, wanted in (("user_product", {"user_product", "stock"}), ("family", {"family"})):
            plan = bundle.plan(("bundle",), enabled, frozenset({"promotions"}), kind=kind)
            assert set(plan.wanted) == wanted and plan.dropped == frozenset(), kind

    def test_the_bundle_of_an_item_still_drops_what_it_cannot_fetch(self) -> None:
        plan = bundle.plan(("bundle",), ["core", "promotions", "visits"], frozenset({"promotions"}))
        assert plan.dropped == {"promotions", "visits"}

    def test_a_disabled_user_product_resource_is_dropped_on_its_own_entry(self) -> None:
        plan = bundle.plan(("stock",), ["core"], kind="user_product")
        assert dict(plan.wanted) == {} and plan.dropped == {"stock"}


class TestKeyValidity:
    @pytest.mark.parametrize("key", ["1", "5385385211222674", str(2**63 - 1)])
    def test_a_bigint_family_id_is_valid(self, key) -> None:
        assert bundle.is_valid_key("family", key) is True

    @pytest.mark.parametrize("key", ["", "abc", "-1", "1.5", " 7", str(2**63), "٣", "007", "00"])
    def test_anything_else_is_not_a_family_id(self, key) -> None:
        assert bundle.is_valid_key("family", key) is False

    @pytest.mark.parametrize("resource", ["user_product", "stock", "description", "prices"])
    def test_text_keyed_resources_hold_any_id(self, resource) -> None:
        assert bundle.is_valid_key(resource, "whatever") is True


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
