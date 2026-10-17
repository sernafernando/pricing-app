"""Who caused an event or a history entry (eventos-historial-legibles T3): the pure rules of `view/origin.py`.

Events and change-log rows are the captured production rows of MLA1402898289 (`history_events_...json`); the audit
rows have the shapes their writers leave (`ml_write_log` from the promotions write service, `auditoria` from PxQ and
the product links, `free_shipping_fix_log` from the auto fix). No database here: `origin.of_event`/`of_entry` decide
from the rows they are given; the Postgres test covers the read that feeds them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.services.ml_publications.events import EVENT_TYPES
from app.services.ml_publications.view import origin
from app.services.ml_publications.view.origin import (
    AUTOMATICO,
    ML,
    NOSOTROS,
    SIN_REGISTRAR,
    SOURCE_FREE_SHIPPING,
    SOURCE_LINK,
    SOURCE_PROMOTION,
    SOURCE_PXQ,
    Audit,
)
from tests.services.ml_publications.conftest import load_fixture

CAPTURE = "history_events_MLA1402898289_20261016.json"
AT = datetime(2026, 10, 13, 19, 11, 18, tzinfo=timezone.utc)
CAPTURED = load_fixture(CAPTURE)
EVENTS = {e["id"]: e for e in CAPTURED["events"]}
LOG = {row["id"]: row for row in CAPTURED["change_log"]}


def event(event_id: int, at: datetime = AT) -> dict[str, Any]:
    return {**EVENTS[event_id], "observed_at": at}


def entry(log_id: int, at: datetime = AT, **extra: Any) -> dict[str, Any]:
    row = LOG[log_id]
    return {"resource_type": row["resource_type"], "changes": row["changes"], "observed_at": at, **extra}


def enroll(target: str, minutes_before: float, user: str | None = "Ana Pérez", action: str = "enroll") -> Audit:
    return Audit(
        SOURCE_PROMOTION,
        AT - timedelta(minutes=minutes_before),
        action=action,
        target_id=target,
        user_name=user,
        has_user=user is not None,
    )


def verdict(kind: str, user_name: str | None = None, informational: bool = False) -> origin.Verdict:
    return origin.Verdict(kind, user_name, informational)


class TestClassification:
    def test_every_event_type_of_the_rules_is_classified_explicitly(self) -> None:
        """A type added to `events.EVENT_TYPES` without a rule here fails this test, not the screen."""
        assert set(origin.EVENT_RULES) == set(EVENT_TYPES) and len(EVENT_TYPES) == 22
        assert {rule.fallback for rule in origin.EVENT_RULES.values()} <= set(origin.KINDS)

    @pytest.mark.parametrize(
        "event_type",
        [
            "promotion_offered",
            "catalog_competition_won",
            "catalog_competition_lost",
            "moderation_applied",
            "moderation_resolved",
            "status_under_review",
            "sub_status_changed",
        ],
    )
    def test_the_changes_ml_makes_by_nature_are_ml(self, event_type: str) -> None:
        assert origin.EVENT_RULES[event_type].fallback == ML

    @pytest.mark.parametrize(
        "event_type",
        [
            "status_paused",
            "status_activated",
            "status_closed",
            "status_changed_other",
            "stock_depleted",
            "stock_replenished",
            "price_changed",
            "promotion_activated",
            "promotion_price_changed",
            "title_changed",
            "listing_type_changed",
            "item_gone",
            "item_restored",
        ],
    )
    def test_a_change_that_could_be_ours_or_ml_s_is_never_ml_by_nature(self, event_type: str) -> None:
        assert origin.EVENT_RULES[event_type].fallback == SIN_REGISTRAR

    def test_only_offers_are_informational_by_type(self) -> None:
        assert {t for t, rule in origin.EVENT_RULES.items() if rule.informational} == {"promotion_offered"}

    def test_the_window_is_a_bounded_positive_interval(self) -> None:
        assert timedelta(0) < origin.ORIGIN_WINDOW <= timedelta(hours=1)


class TestEvents:
    def test_an_offer_is_ml_and_informational_even_next_to_our_writes(self) -> None:
        offered = event(6378)
        assert origin.of_event(offered, [enroll("C-MLA1717457", 1)]) == verdict(ML, informational=True)

    def test_an_activation_after_our_enroll_of_that_promotion_is_ours_with_the_user(self) -> None:
        activated = event(3689)  # promotion_activated C-MLA1717163
        assert origin.of_event(activated, [enroll("C-MLA1717163", 5)]) == verdict(NOSOTROS, "Ana Pérez")

    def test_an_enroll_of_another_promotion_does_not_count(self) -> None:
        assert origin.of_event(event(3689), [enroll("C-MLA1664342", 5)]) == verdict(SIN_REGISTRAR)

    def test_an_enroll_older_than_the_window_does_not_count(self) -> None:
        old = origin.ORIGIN_WINDOW.total_seconds() / 60 + 1
        assert origin.of_event(event(3689), [enroll("C-MLA1717163", old)]) == verdict(SIN_REGISTRAR)

    def test_an_enroll_after_the_event_does_not_count(self) -> None:
        assert origin.of_event(event(3689), [enroll("C-MLA1717163", -1)]) == verdict(SIN_REGISTRAR)

    def test_the_edges_of_the_window_count(self) -> None:
        edge = origin.ORIGIN_WINDOW.total_seconds() / 60
        assert origin.of_event(event(3689), [enroll("C-MLA1717163", edge)]).kind == NOSOTROS
        assert origin.of_event(event(3689), [enroll("C-MLA1717163", 0)]).kind == NOSOTROS

    def test_a_write_without_user_is_automatic(self) -> None:
        assert origin.of_event(event(3689), [enroll("C-MLA1717163", 5, user=None)]) == verdict(AUTOMATICO)

    def test_the_latest_matching_write_decides(self) -> None:
        audits = [enroll("C-MLA1717163", 20, user="Beto"), enroll("C-MLA1717163", 3, user=None)]
        assert origin.of_event(event(3689), audits) == verdict(AUTOMATICO)

    def test_a_removal_needs_our_remove_not_an_enroll(self) -> None:
        finished = event(43804)  # promotion_finished C-MLA1717163, it had been started
        assert origin.of_event(finished, [enroll("C-MLA1717163", 2)]) == verdict(SIN_REGISTRAR)
        assert origin.of_event(finished, [enroll("C-MLA1717163", 2, action="remove")]) == verdict(NOSOTROS, "Ana Pérez")

    def test_a_candidate_no_longer_offered_is_ml_and_informational(self) -> None:
        assert origin.of_event(event(6376), []) == verdict(ML, informational=True)

    def test_a_started_promotion_that_finished_without_our_remove_is_unregistered(self) -> None:
        assert origin.of_event(event(43804), []) == verdict(SIN_REGISTRAR)

    def test_the_sale_and_promotion_price_follow_our_promotion_write_whatever_its_target(self) -> None:
        """Enrolling or removing a promotion moves the sale price, whose id is the offer's, not the campaign's."""
        audits = [enroll("C-MLA1717163", 4, action="remove")]
        assert origin.of_event(event(43805), audits) == verdict(NOSOTROS, "Ana Pérez")  # sale price
        assert origin.of_event(event(43803), audits) == verdict(NOSOTROS, "Ana Pérez")  # promotion price

    def test_the_standard_price_has_no_audit_of_ours_and_stays_unregistered(self) -> None:
        assert origin.of_event(event(43802), [enroll("C-MLA1717163", 4)]) == verdict(SIN_REGISTRAR)

    @pytest.mark.parametrize("event_id", [42330, 43638, 3195])  # paused, activated, stock replenished
    def test_never_ours_without_an_audit_row(self, event_id: int) -> None:
        assert origin.of_event(event(event_id), []) == verdict(SIN_REGISTRAR)

    def test_an_unknown_type_is_unregistered(self) -> None:
        unknown = {**event(42330), "event_type": "something_new"}
        assert origin.of_event(unknown, [enroll("C-MLA1717163", 1)]) == verdict(SIN_REGISTRAR)


def link_event(source_new: str = "sku_auto", linked_by: Any = None, variation_id: int = 0) -> dict[str, Any]:
    """`product_link_changed` with the payload `events._product_link_events` copies from the row's context
    (production row of MLA3505165240:0, 2026-10-17)."""
    return {
        "event_type": "product_link_changed",
        "observed_at": AT,
        "promotion_id": None,
        "price_kind": None,
        "old_value": 318,
        "new_value": None,
        "payload": {
            "variation_id": variation_id,
            "source_old": "sku_auto",
            "source_new": source_new,
            "match_status_old": "linked",
            "match_status_new": "unmatched",
            "matched_sku": "318",
            "sku_field": "seller_sku_attr",
            "linked_by": linked_by,
        },
    }


def link_audit(variation_id: str = "0", minutes_before: float = 0) -> Audit:
    return Audit(
        SOURCE_LINK,
        AT - timedelta(minutes=minutes_before),
        action="ML_VINCULO_MANUAL",
        target_id=variation_id,
        user_name="Carla",
        has_user=True,
    )


class TestLinks:
    def test_a_link_change_with_our_audit_row_is_ours(self) -> None:
        assert origin.of_event(link_event("manual", 7), [link_audit()]) == verdict(NOSOTROS, "Carla")

    def test_the_audit_of_another_variation_does_not_count(self) -> None:
        assert origin.of_event(link_event("manual", 7), [link_audit("1")]).kind == SIN_REGISTRAR

    def test_the_sku_rule_with_no_audit_row_is_automatic(self) -> None:
        """Every operator decision writes its `auditoria` row in the link change's own transaction (links.py), so a
        change the SKU rule made (`source_new` sku_auto, no author) is the worker's."""
        assert origin.of_event(link_event(), []) == verdict(AUTOMATICO)

    def test_a_manual_link_without_its_audit_row_is_unregistered(self) -> None:
        assert origin.of_event(link_event("manual", 7), []) == verdict(SIN_REGISTRAR)


class TestEntries:
    def test_a_promotions_row_of_suggested_prices_and_new_candidates_is_ml_and_informational(self) -> None:
        assert origin.of_entry(entry(9282), []) == verdict(ML, informational=True)

    def test_a_promotions_row_where_a_promotion_started_follows_our_enroll_of_it(self) -> None:
        started = entry(7672)  # adds [C-MLA1717163], started
        assert origin.of_entry(started, [enroll("C-MLA1717163", 6)]) == verdict(NOSOTROS, "Ana Pérez")
        assert origin.of_entry(started, [enroll("C-MLA9999999", 6)]) == verdict(SIN_REGISTRAR)
        assert origin.of_entry(started, []) == verdict(SIN_REGISTRAR)

    def test_prices_rows_follow_a_promotion_write_or_a_pxq_publish(self) -> None:
        pxq = Audit(
            SOURCE_PXQ, AT - timedelta(minutes=2), action="PXQ_PRECIO_PUBLICADO", user_name="Dani", has_user=True
        )
        assert origin.of_entry(entry(7671), [pxq]) == verdict(NOSOTROS, "Dani")
        assert origin.of_entry(entry(7673), [enroll("C-MLA1717163", 1)]) == verdict(NOSOTROS, "Ana Pérez")
        assert origin.of_entry(entry(7671), []) == verdict(SIN_REGISTRAR)

    @pytest.mark.parametrize("log_id, informational", [(34965, True), (172543, True), (140177, False)])
    def test_ml_side_resources_are_ml(self, log_id: int, informational: bool) -> None:
        assert origin.of_entry(entry(log_id), [enroll("C-MLA1717163", 1)]) == verdict(ML, informational=informational)

    @pytest.mark.parametrize("log_id", [6989, 70046, 175494])  # item, item price, stock
    def test_item_and_stock_rows_without_audit_are_unregistered(self, log_id: int) -> None:
        assert origin.of_entry(entry(log_id), []) == verdict(SIN_REGISTRAR)

    def test_a_product_link_row_follows_the_audit_of_its_variation(self) -> None:
        link = entry(6989, resource_type="product_link", entity_id="MLA1402898289:0", link_source="manual")
        link["changes"] = [{"p": "producto_item_id", "op": "replace", "new": 318, "old": None}]
        assert origin.of_entry(link, [link_audit("0")]) == verdict(NOSOTROS, "Carla")
        assert origin.of_entry(link, [link_audit("3")]) == verdict(SIN_REGISTRAR)
        assert origin.of_entry({**link, "link_source": "sku_auto"}, []) == verdict(AUTOMATICO)


# Production row 204983 (MLA3958593392, 2026-10-17): ML turned free shipping ON along with a price change.
FREE_SHIPPING_ON = [
    {"p": "base_price", "op": "replace", "new": 47760.0, "old": 26493.91},
    {"p": "last_updated", "op": "replace", "new": "2026-10-17T13:57:05.756Z", "old": "2026-10-17T13:55:58.735Z"},
    {"p": "price", "op": "replace", "new": 47760.0, "old": 26493.91},
    {"p": "shipping.free_shipping", "op": "replace", "new": True, "old": False},
    {"p": "shipping.tags[=mandatory_free_shipping]", "op": "add", "new": "mandatory_free_shipping"},
]


class TestFreeShipping:
    def fix(self) -> Audit:
        return Audit(SOURCE_FREE_SHIPPING, AT - timedelta(minutes=3))

    def test_our_fix_turning_free_shipping_off_is_automatic(self) -> None:
        off = [
            {
                "p": "last_updated",
                "op": "replace",
                "new": "2026-10-17T13:57:05.756Z",
                "old": "2026-10-17T13:55:58.735Z",
            },
            {"p": "shipping.free_shipping", "op": "replace", "new": False, "old": True},
        ]
        row = {"resource_type": "item", "changes": off, "observed_at": AT}
        assert origin.of_entry(row, [self.fix()]) == verdict(AUTOMATICO)

    def test_a_row_that_also_moves_a_business_field_is_not_claimed_by_the_fix(self) -> None:
        mixed = [
            {**c, "new": False, "old": True} if c["p"] == "shipping.free_shipping" else c for c in FREE_SHIPPING_ON
        ]
        row = {"resource_type": "item", "changes": mixed, "observed_at": AT}
        assert origin.of_entry(row, [self.fix()]) == verdict(SIN_REGISTRAR)

    def test_free_shipping_turned_on_is_not_our_fix(self) -> None:
        on = [c for c in FREE_SHIPPING_ON if c["p"].startswith(("shipping", "last_updated"))]
        row = {"resource_type": "item", "changes": on, "observed_at": AT}
        assert origin.of_entry(row, [self.fix()]) == verdict(SIN_REGISTRAR)


class TestClaims:
    """What the loader reads: only the window behind the events that can match an audit row."""

    def test_events_that_cannot_match_need_no_read(self) -> None:
        assert origin.span([origin.event_claim(event(6378)), origin.event_claim(event(42330))]) is None

    def test_the_span_covers_every_claim_and_its_window(self) -> None:
        early, late = AT - timedelta(days=2), AT
        claims = [origin.event_claim(event(3689, early)), origin.event_claim(event(43804, late))]
        assert origin.span(claims) == (early - origin.ORIGIN_WINDOW, late)
