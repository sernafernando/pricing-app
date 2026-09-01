"""
RED/GREEN — `app.services.ml_orders_ingestion.mapper` (ml-ventas-fuente-de-verdad,
slice 2).

Pure mapping, no I/O, no DB. Spec coverage:
  REQ-1 — happy path: full ML order payload maps to `OrderOpsDTO`
          (order fields + nested `OrderItemOpsDTO` list), tz-naive-to-aware
          conversion on every timestamp.
  REQ-2 — missing required field (`id`, `date_last_updated`, `seller.id`)
          -> `MappingError`, never a partially-populated DTO
          (fail-closed contract, design D7).
  REQ-3 — extra/unknown fields in the payload are ignored, not an error.
  REQ-4 — `map_shipment` happy path + missing required field -> MappingError.
"""

from __future__ import annotations

from datetime import timezone

from app.services.ml_orders_ingestion.mapper import (
    MappingError,
    OrderItemOpsDTO,
    OrderOpsDTO,
    ShipmentOpsDTO,
    map_order,
    map_shipment,
)

FULL_ORDER_PAYLOAD = {
    "id": 2000003508498841,
    "pack_id": None,
    "status": "paid",
    "status_detail": None,
    "date_created": "2026-08-01T10:00:00.000-03:00",
    "date_closed": "2026-08-01T10:05:00.000-03:00",
    "date_last_updated": "2026-08-01T10:05:00.000-03:00",
    "buyer": {"id": 111, "nickname": "COMPRADOR1"},
    "seller": {"id": 456},
    "total_amount": 1000.50,
    "paid_amount": 1000.50,
    "currency_id": "ARS",
    "shipping": {"id": 40000012345},
    "tags": ["not_delivered"],
    "order_items": [
        {
            "item": {
                "id": "MLA123456789",
                "title": "Producto de prueba",
                "variation_id": None,
                "seller_sku": "SKU-1",
            },
            "quantity": 2,
            "unit_price": 500.25,
            "full_unit_price": 600.00,
            "sale_fee": 45.5,
            "listing_type_id": "gold_special",
        }
    ],
    "some_unmapped_field_from_ml": {"nested": True},
}


class TestMapOrderHappyPath:
    def test_maps_all_scalar_fields(self) -> None:
        result = map_order(FULL_ORDER_PAYLOAD)

        assert isinstance(result, OrderOpsDTO)
        assert result.order_id == 2000003508498841
        assert result.pack_id is None
        assert result.status == "paid"
        assert result.status_detail is None
        assert result.buyer_id == 111
        assert result.buyer_nickname == "COMPRADOR1"
        assert result.seller_id == 456
        assert result.total_amount == 1000.50
        assert result.paid_amount == 1000.50
        assert result.currency_id == "ARS"
        assert result.shipping_id == 40000012345
        assert result.tags == ["not_delivered"]
        assert result.raw_order == FULL_ORDER_PAYLOAD

    def test_timestamps_are_tz_aware(self) -> None:
        result = map_order(FULL_ORDER_PAYLOAD)

        assert isinstance(result, OrderOpsDTO)
        assert result.date_created.tzinfo is not None
        assert result.date_closed.tzinfo is not None
        assert result.ml_last_updated.tzinfo is not None
        assert result.ml_last_updated.astimezone(timezone.utc).hour == 13

    def test_maps_items(self) -> None:
        result = map_order(FULL_ORDER_PAYLOAD)

        assert isinstance(result, OrderOpsDTO)
        assert len(result.items) == 1
        item = result.items[0]
        assert isinstance(item, OrderItemOpsDTO)
        assert item.item_id == "MLA123456789"
        assert item.variation_id is None
        assert item.seller_sku == "SKU-1"
        assert item.title == "Producto de prueba"
        assert item.quantity == 2
        assert item.unit_price == 500.25
        assert item.full_unit_price == 600.00
        assert item.sale_fee == 45.5
        assert item.listing_type_id == "gold_special"
        assert item.raw_item == FULL_ORDER_PAYLOAD["order_items"][0]

    def test_extra_unknown_fields_are_ignored(self) -> None:
        result = map_order(FULL_ORDER_PAYLOAD)

        assert isinstance(result, OrderOpsDTO)
        # No AttributeError, no crash — the DTO simply doesn't carry it
        # as a typed field (it is still retained in raw_order above).
        assert not hasattr(result, "some_unmapped_field_from_ml")

    def test_order_with_no_shipping_maps_shipping_id_none(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "shipping": None}
        result = map_order(payload)

        assert isinstance(result, OrderOpsDTO)
        assert result.shipping_id is None

    def test_order_with_no_items_maps_empty_list(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "order_items": []}
        result = map_order(payload)

        assert isinstance(result, OrderOpsDTO)
        assert result.items == []


class TestMapOrderFailClosed:
    def test_missing_id_returns_mapping_error(self) -> None:
        payload = {k: v for k, v in FULL_ORDER_PAYLOAD.items() if k != "id"}
        result = map_order(payload)

        assert isinstance(result, MappingError)
        assert not isinstance(result, OrderOpsDTO)

    def test_missing_date_last_updated_returns_mapping_error(self) -> None:
        payload = {k: v for k, v in FULL_ORDER_PAYLOAD.items() if k != "date_last_updated"}
        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_missing_seller_returns_mapping_error(self) -> None:
        payload = {k: v for k, v in FULL_ORDER_PAYLOAD.items() if k != "seller"}
        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_unparseable_date_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "date_last_updated": "not-a-date"}
        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_empty_payload_returns_mapping_error(self) -> None:
        result = map_order({})

        assert isinstance(result, MappingError)

    def test_mapping_error_carries_reason_and_raw_payload(self) -> None:
        payload = {k: v for k, v in FULL_ORDER_PAYLOAD.items() if k != "id"}
        result = map_order(payload)

        assert isinstance(result, MappingError)
        assert result.reason
        assert result.raw_payload == payload


FULL_SHIPMENT_PAYLOAD = {
    "id": 40000012345,
    "order_id": 2000003508498841,
    "status": "delivered",
    "substatus": "delivered",
    "logistic_type": "cross_docking",
    "tracking_number": "TRACK123",
    "tracking_method": "correo",
    "date_created": "2026-08-01T10:06:00.000-03:00",
    "last_updated": "2026-08-02T09:00:00.000-03:00",
    "receiver_address": {"city": "CABA"},
}


class TestMapShipment:
    def test_happy_path(self) -> None:
        result = map_shipment(FULL_SHIPMENT_PAYLOAD)

        assert isinstance(result, ShipmentOpsDTO)
        assert result.shipment_id == 40000012345
        assert result.order_id == 2000003508498841
        assert result.status == "delivered"
        assert result.substatus == "delivered"
        assert result.logistic_type == "cross_docking"
        assert result.tracking_number == "TRACK123"
        assert result.tracking_method == "correo"
        assert result.date_created.tzinfo is not None
        assert result.last_updated.tzinfo is not None
        assert result.receiver_address == {"city": "CABA"}
        assert result.raw_shipment == FULL_SHIPMENT_PAYLOAD

    def test_missing_id_returns_mapping_error(self) -> None:
        payload = {k: v for k, v in FULL_SHIPMENT_PAYLOAD.items() if k != "id"}
        result = map_shipment(payload)

        assert isinstance(result, MappingError)
        assert not isinstance(result, ShipmentOpsDTO)

    def test_empty_payload_returns_mapping_error(self) -> None:
        result = map_shipment({})

        assert isinstance(result, MappingError)


class TestMapOrderContractHoles:
    """The mapper documents that it never raises. These cover the paths
    where that contract used to leak through as an exception."""

    def test_unparseable_shipping_id_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "shipping": {"id": "abc"}}

        result = map_order(payload)

        assert isinstance(result, MappingError)
        assert "shipping" in result.reason

    def test_order_items_as_list_of_strings_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "order_items": ["not-a-dict"]}

        result = map_order(payload)

        assert isinstance(result, MappingError)
        assert "order_items" in result.reason

    def test_order_items_item_not_a_dict_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "order_items": [{"item": "not-a-dict"}]}

        result = map_order(payload)

        assert isinstance(result, MappingError)
        assert "order_items" in result.reason


class TestMapOrderContractHolesRound2:
    """Second round of contract holes: a payload whose sub-objects or
    scalars have the wrong TYPE must still come back as a MappingError,
    and a required field must never end up silently empty."""

    def test_non_string_timestamp_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "date_last_updated": 1754049600}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_non_dict_seller_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "seller": "456"}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_non_dict_shipping_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "shipping": "40000012345"}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_non_dict_buyer_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "buyer": "789"}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_empty_required_timestamp_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "date_last_updated": ""}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_item_without_id_returns_mapping_error_not_the_string_none(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "order_items": [{"item": {"title": "no id"}, "quantity": 1}]}

        result = map_order(payload)

        assert isinstance(result, MappingError)

    def test_non_string_shipment_timestamp_returns_mapping_error(self) -> None:
        result = map_shipment({"id": 40000012345, "last_updated": 1754049600})

        assert isinstance(result, MappingError)


class TestMapperRootPayloadShape:
    """`response.json()` can legitimately return a list or a string. The
    root payload guard was `if not payload`, which those pass."""

    def test_list_payload_returns_mapping_error(self) -> None:
        assert isinstance(map_order([{"id": 1}]), MappingError)  # type: ignore[arg-type]

    def test_string_payload_returns_mapping_error(self) -> None:
        assert isinstance(map_order("error"), MappingError)  # type: ignore[arg-type]

    def test_shipment_list_payload_returns_mapping_error(self) -> None:
        assert isinstance(map_shipment([{"id": 1}]), MappingError)  # type: ignore[arg-type]

    def test_shipment_string_payload_returns_mapping_error(self) -> None:
        assert isinstance(map_shipment("error"), MappingError)  # type: ignore[arg-type]

    def test_non_list_tags_returns_mapping_error(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "tags": "paid"}

        assert isinstance(map_order(payload), MappingError)


class TestVariationIdCoercion:
    """`variation_id` is annotated Optional[int] but ML sometimes sends it
    as a string, so the annotation has to be made true rather than assumed."""

    def test_string_variation_id_is_coerced_to_int(self) -> None:
        payload = {
            **FULL_ORDER_PAYLOAD,
            "order_items": [{"item": {"id": "MLA123", "variation_id": "987"}, "quantity": 1}],
        }

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.items[0].variation_id == 987

    def test_unparseable_variation_id_returns_mapping_error(self) -> None:
        payload = {
            **FULL_ORDER_PAYLOAD,
            "order_items": [{"item": {"id": "MLA123", "variation_id": "abc"}, "quantity": 1}],
        }

        assert isinstance(map_order(payload), MappingError)


class TestPaymentStatusAndCoveredByMarketplace:
    """ml-ventas-listado: `payment_status` (`payments[0].status`) and
    `covered_by_marketplace` (currently always `None`, undetermined --
    see `map_order`'s inline comment)."""

    def test_payment_status_read_from_first_payment(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "payments": [{"status": "in_mediation"}, {"status": "approved"}]}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status == "in_mediation"

    def test_payment_status_none_when_no_payments(self) -> None:
        result = map_order(FULL_ORDER_PAYLOAD)

        assert not isinstance(result, MappingError)
        assert result.payment_status is None

    def test_payment_status_none_when_payments_not_a_list(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "payments": "not-a-list"}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status is None

    def test_payment_status_none_when_first_payment_not_a_dict(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "payments": ["not-a-dict"]}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status is None

    def test_covered_by_marketplace_is_always_none(self) -> None:
        """No verified field/tag exists for this yet -- see `map_order`'s
        inline comment. This test pins the honest current behaviour so a
        future slice that fills it in has to deliberately change this."""
        result = map_order(FULL_ORDER_PAYLOAD)

        assert not isinstance(result, MappingError)
        assert result.covered_by_marketplace is None


class TestUnknownPaymentStatusIsDropped:
    """`payment_status` has a closed CHECK in Postgres. A value ML has not
    used before would raise IntegrityError on insert and take the whole
    batch with it, breaking `upsert_order`'s "never raises" contract. SQLite
    does not enforce the constraint, so nothing here would show it."""

    def test_a_status_outside_the_vocabulary_becomes_none(self) -> None:
        from app.models.ml_orders_ops import PAYMENT_STATUSES

        payload = {**FULL_ORDER_PAYLOAD, "payments": [{"status": "a_status_ml_invented"}]}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status is None
        assert "a_status_ml_invented" not in PAYMENT_STATUSES

    def test_a_known_status_survives(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "payments": [{"status": "in_mediation"}]}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status == "in_mediation"

    def test_a_non_string_status_becomes_none(self) -> None:
        payload = {**FULL_ORDER_PAYLOAD, "payments": [{"status": 42}]}

        result = map_order(payload)

        assert not isinstance(result, MappingError)
        assert result.payment_status is None
