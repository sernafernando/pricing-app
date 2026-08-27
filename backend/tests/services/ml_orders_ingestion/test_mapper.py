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
