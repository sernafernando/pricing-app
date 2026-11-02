"""ml-ads-cupones-display T3a -- mapping of the real `GET /orders/{id}/discounts` bodies."""

from __future__ import annotations

import copy
from decimal import Decimal

from app.services.ml_order_discounts import mapper
from tests.services.ml_order_discounts.conftest import fixture


class TestClassify:
    def test_a_body_with_details_is_ok(self) -> None:
        assert mapper.classify(200, fixture("discounts_top_coupon_1")) == mapper.OK

    def test_the_real_404_is_none(self) -> None:
        assert mapper.classify(404, fixture("discounts_not_found")) == mapper.NONE

    def test_a_404_body_inside_a_200_is_none_and_reports_the_body_status(self) -> None:
        body = fixture("discounts_not_found")  # real body, wrapped in a 200 as the proxy can
        assert mapper.classify(200, body) == mapper.NONE
        assert mapper.body_status(200, body) == 404

    def test_a_200_without_details_or_a_500_is_an_error(self) -> None:
        assert mapper.classify(200, {"unexpected": True}) == mapper.ERROR
        assert mapper.classify(500, None) == mapper.ERROR


class TestLines:
    def test_one_ml_funded_coupon_and_the_seller_offer(self) -> None:
        lines = mapper.map_lines(1, fixture("discounts_top_coupon_1"))
        assert [(line.type, line.detail_index, line.item_index) for line in lines] == [
            ("coupon", 0, 0),
            ("discount", 1, 0),
        ]
        coupon, offer = lines
        assert coupon.coupon_id == coupon.campaign_id == 2251816913499998
        assert coupon.meli_campaign == "P-MLA18109016"
        assert (coupon.amount_seller, coupon.amount_total) == (Decimal("0.00"), Decimal("137937.00"))
        assert (coupon.item_id, coupon.element_id, coupon.quantity) == ("MLA3731221138", 1, 1)
        assert coupon.funding_mode is None and coupon.offer_id is None
        assert offer.coupon_id is None and offer.funding_mode == "seller"
        assert offer.offer_id == "OFFER-MLA3731221138-11557155858"
        assert offer.amount_seller == offer.amount_total == Decimal("1396741.00")

    def test_a_seller_funded_coupon_has_seller_equal_total_and_no_meli_campaign(self) -> None:
        seller, ml, _offer = mapper.map_lines(2, fixture("discounts_top_coupon_2"))
        assert seller.coupon_id == 2251816907406672 and seller.meli_campaign is None
        assert seller.amount_seller == seller.amount_total == Decimal("20000.00")
        assert ml.meli_campaign == "P-MLA18091086" and ml.amount_seller == Decimal("0.00")

    def test_three_coupons_keep_their_cents(self) -> None:
        lines = mapper.map_lines(3, fixture("discounts_top_coupon_3"))
        assert [line.type for line in lines] == ["coupon", "coupon", "coupon", "discount"]
        assert lines[2].amount_total == Decimal("42382.77")
        assert lines[1].meli_campaign is None and lines[1].amount_seller == Decimal("0.00")

    def test_a_404_body_has_no_lines_and_an_odd_shape_is_skipped_not_raised(self) -> None:
        assert mapper.map_lines(4, fixture("discounts_not_found")) == []
        body = copy.deepcopy(fixture("discounts_top_coupon_1"))  # perturbed copy of a real body
        body["details"].insert(0, "not a detail")
        body["details"][1]["items"].append(None)
        body["details"][1]["coupon"] = {"id": True}
        lines = mapper.map_lines(5, body)
        assert [line.detail_index for line in lines] == [1, 2]
        assert lines[0].coupon_id is None
