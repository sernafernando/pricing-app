"""Tests for tn_image_normalizer.extract: GBP report-78 x TN product join."""

import inspect

from sqlalchemy.orm import Session

from app.services.tn_image_normalizer.extract import (
    STATE_NO_SOURCE_IMAGES,
    STATE_PENDING,
    ItemPlan,
    TnProductRef,
    extract_item_plans,
)


def _report_row(ean: str, **images: str) -> dict:
    row = {"Código": ean}
    row.update(images)
    return row


def _product(product_id: int, variant_sku: str | None, activo: bool = True) -> TnProductRef:
    return TnProductRef(product_id=product_id, variant_sku=variant_sku, activo=activo)


class TestPurity:
    def test_extract_function_never_declares_a_session_parameter(self) -> None:
        signature = inspect.signature(extract_item_plans)
        for param in signature.parameters.values():
            assert param.annotation is not Session

    def test_extract_returns_frozen_plain_data(self) -> None:
        plans = extract_item_plans(
            [_report_row("23942321477", image1="https://x/a.jpg")],
            [_product(1, "23942321477")],
        )
        assert len(plans) == 1
        assert isinstance(plans[0], ItemPlan)


class TestMatchingAndOrdering:
    def test_matching_ean_yields_one_row_per_populated_slot_in_order(self) -> None:
        row = _report_row(
            "111",
            image1="https://x/1.jpg",
            image2="https://x/2.jpg",
            image3="https://x/3.jpg",
        )
        plans = extract_item_plans([row], [_product(1, "111")])

        assert [p.source_slot for p in plans] == [1, 2, 3]
        assert [p.source_url for p in plans] == [
            "https://x/1.jpg",
            "https://x/2.jpg",
            "https://x/3.jpg",
        ]
        assert all(p.ean == "111" and p.tn_product_id == 1 for p in plans)
        assert all(p.state == STATE_PENDING for p in plans)

    def test_empty_slots_are_skipped_without_shifting_remaining_slot_numbers(self) -> None:
        row = _report_row(
            "222",
            image1="",
            image2="https://x/2.jpg",
            image3="   ",
            image4="https://x/4.jpg",
        )
        plans = extract_item_plans([row], [_product(1, "222")])

        assert [p.source_slot for p in plans] == [2, 4]
        assert [p.source_url for p in plans] == ["https://x/2.jpg", "https://x/4.jpg"]

    def test_leading_zero_tolerance_matches_report_ean_to_variant_sku(self) -> None:
        row = _report_row("023942321477", image1="https://x/1.jpg")
        plans = extract_item_plans([row], [_product(1, "23942321477")])

        assert len(plans) == 1
        assert plans[0].ean == "23942321477"
        assert plans[0].tn_product_id == 1

    def test_unmatched_ean_yields_nothing(self) -> None:
        row = _report_row("999999", image1="https://x/1.jpg")
        plans = extract_item_plans([row], [_product(1, "111111")])

        assert plans == []


class TestSentinelNonCollision:
    def test_two_blank_codigo_rows_and_a_blank_variant_sku_produce_no_join(self) -> None:
        rows = [
            _report_row("", image1="https://x/1.jpg"),
            _report_row("   ", image1="https://x/2.jpg"),
        ]
        products = [_product(1, ""), _product(2, None)]

        plans = extract_item_plans(rows, products)

        assert plans == []

    def test_non_numeric_sku_never_matches_anything_including_itself(self) -> None:
        rows = [_report_row("ABC123", image1="https://x/1.jpg")]
        products = [_product(1, "ABC123")]

        plans = extract_item_plans(rows, products)

        assert plans == []


class TestActivoTrap:
    def test_inactive_product_is_excluded_despite_perfect_sku_match(self) -> None:
        row = _report_row("333", image1="https://x/1.jpg")
        plans = extract_item_plans([row], [_product(1, "333", activo=False)])

        assert plans == []


class TestNoSourceImages:
    def test_zero_image_matching_product_yields_one_reviewable_row(self) -> None:
        row = _report_row("444")
        plans = extract_item_plans([row], [_product(1, "444")])

        assert len(plans) == 1
        plan = plans[0]
        assert plan.state == STATE_NO_SOURCE_IMAGES
        assert plan.ean == "444"
        assert plan.tn_product_id == 1
        assert plan.source_url is None
