"""Sale price parser and mapper, over the captured `/items/{id}/sale_price?context=channel_marketplace`."""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime

import pytest

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.sale_price import map_sale_price, parse_sale_price
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from tests.services.ml_publications.conftest import subresource_body, subresource_call


def test_200_is_ok_and_keeps_the_body():
    body = subresource_body("sale_price", "sale_price_MLA874027718")
    parsed = parse_sale_price(200, body)
    assert parsed.state == "ok" and parsed.body == body


def test_without_promotion_metadata_is_empty():
    body = subresource_body("sale_price", "sale_price_MLA874027718")
    assert body["metadata"] == {}
    assert map_sale_price(body) == {
        "price_id": "465",
        "amount": Decimal("55882.0"),
        "regular_amount": None,
        "currency_id": "ARS",
        "campaign_id": None,
        "promotion_id": None,
        "promotion_type": None,
    }


def test_with_promotion_metadata():
    typed = map_sale_price(subresource_body("sale_price", "sale_price_started_MLA2146576013"))
    assert typed == {
        "price_id": "7",
        "amount": Decimal("1509999.0"),
        "regular_amount": Decimal("2381471.0"),
        "currency_id": "ARS",
        "campaign_id": "C-MLA1669550",
        "promotion_id": "OFFER-MLA2146576013-11568619123",
        "promotion_type": "custom",
    }


def test_reference_date_is_the_response_time_so_it_is_not_a_typed_column():
    """The captured `reference_date` equals the response `Date` header on every call: it moves on
    each fetch with no state change, so no typed column carries it (it stays in raw)."""
    for name in (
        "sale_price_MLA874027718",
        "sale_price_MLA903301838",
        "sale_price_started_MLA2146576013",
        "sale_price_candidate_MLA2146646463",
    ):
        call = subresource_call("sale_price", name)
        header = parsedate_to_datetime(call["headers"]["date"])
        assert to_timestamp(call["body"]["reference_date"]) == header.astimezone(timezone.utc), name
        assert "reference_date" not in map_sale_price(call["body"])


def test_mapper_tolerates_missing_metadata_real_payload_field_removed():
    body = subresource_body("sale_price", "sale_price_started_MLA2146576013")
    del body["metadata"]
    typed = map_sale_price(body)
    assert typed["promotion_id"] is None and typed["amount"] == Decimal("1509999.0")


def test_non_2xx_is_recorded_synthetic_transport_fault():
    """Synthetic transport fault: no sale_price error was captured."""
    assert parse_sale_price(404, {"message": "x"}).state == "not_found"
    assert parse_sale_price(500, None).state == "error"


@pytest.mark.parametrize("bad", [[], {}, {"price_id": "1"}])
def test_200_without_an_amount_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_sale_price(200, bad)
