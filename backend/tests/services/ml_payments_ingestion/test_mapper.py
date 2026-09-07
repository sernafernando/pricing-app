"""
RED/GREEN — `map_payment` (ml-ventas-desglose-costos, corte 5).

Spec coverage (obs #1960/#1965, measured against 514 real payments):
  REQ-1 — every amount decodes through `Decimal(str(...))`, never
          `float`.
  REQ-2 — unknown/missing top-level fields are IGNORED, not required:
          the proxy can add or drop fields across deploys.
  REQ-3 — a charge line is stored FLAT (`name`, `type`, `amount`,
          `refunded`) -- there is no `amounts.original`/`amounts.refunded`
          nesting in the real payload.
  REQ-4 — `decimal.InvalidOperation` (which is an `ArithmeticError`, NOT
          a `ValueError`) is caught and turned into a `MappingError`,
          never propagated.
  REQ-5 — `map_payment` never raises; it returns a `PaymentDTO` or a
          `MappingError`.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.ml_payments_ingestion.mapper import MappingError, PaymentDTO, map_payment


def _raw_payment(**overrides):
    base = {
        "payment_id": 21000018322969636,
        "order_id": 2000018322969636,
        "status": "approved",
        "currency_id": "ARS",
        "date_approved": "2026-08-01T10:00:00.000-04:00",
        "net_received_amount": 6800.50,
        "total_paid_amount": 7371.11,
        "transaction_amount": 7371.11,
        "shipping_amount": 0,
        "coupon_amount": 0,
        "taxes_amount": 0,
        "transaction_amount_refunded": 0,
        "charges_details": [
            {"name": "mercadopago_fee", "type": "fee", "amount": 570.61, "refunded": 0},
        ],
    }
    base.update(overrides)
    return base


class TestHappyPath:
    def test_maps_every_amount_field_to_decimal(self) -> None:
        result = map_payment(_raw_payment())

        assert isinstance(result, PaymentDTO)
        assert result.payment_id == 21000018322969636
        assert result.order_id == 2000018322969636
        assert result.status == "approved"
        assert result.currency_id == "ARS"
        assert result.net_received_amount == Decimal("6800.50")
        assert result.total_paid_amount == Decimal("7371.11")
        assert result.transaction_amount == Decimal("7371.11")
        assert result.shipping_amount == Decimal("0")
        assert result.coupon_amount == Decimal("0")
        assert result.taxes_amount == Decimal("0")
        assert result.transaction_amount_refunded == Decimal("0")
        assert result.date_approved is not None

    def test_charges_are_flat_dtos(self) -> None:
        result = map_payment(_raw_payment())

        assert isinstance(result, PaymentDTO)
        assert len(result.charges) == 1
        charge = result.charges[0]
        assert charge.name == "mercadopago_fee"
        assert charge.type == "fee"
        assert charge.amount == Decimal("570.61")
        assert charge.refunded == Decimal("0")

    def test_missing_charges_details_yields_empty_list(self) -> None:
        raw = _raw_payment()
        del raw["charges_details"]
        result = map_payment(raw)

        assert isinstance(result, PaymentDTO)
        assert result.charges == []

    def test_raw_payload_is_preserved(self) -> None:
        raw = _raw_payment()
        result = map_payment(raw)

        assert isinstance(result, PaymentDTO)
        assert result.raw_payload == raw


class TestUnknownFieldsIgnored:
    def test_extra_top_level_field_is_ignored(self) -> None:
        raw = _raw_payment(some_new_field_the_proxy_added="whatever")
        result = map_payment(raw)

        assert isinstance(result, PaymentDTO)
        assert result.payment_id == 21000018322969636

    def test_missing_optional_amount_field_defaults_to_none(self) -> None:
        raw = _raw_payment()
        del raw["taxes_amount"]
        result = map_payment(raw)

        assert isinstance(result, PaymentDTO)
        assert result.taxes_amount is None

    def test_missing_optional_charge_field_defaults_to_none(self) -> None:
        raw = _raw_payment(charges_details=[{"name": "financing_fee", "type": "fee", "amount": 100}])
        result = map_payment(raw)

        assert isinstance(result, PaymentDTO)
        assert result.charges[0].refunded is None


class TestFailClosed:
    def test_missing_payment_id_is_mapping_error(self) -> None:
        raw = _raw_payment()
        del raw["payment_id"]
        result = map_payment(raw)

        assert isinstance(result, MappingError)

    def test_missing_order_id_is_mapping_error(self) -> None:
        raw = _raw_payment()
        del raw["order_id"]
        result = map_payment(raw)

        assert isinstance(result, MappingError)

    def test_missing_status_is_mapping_error(self) -> None:
        raw = _raw_payment()
        del raw["status"]
        result = map_payment(raw)

        assert isinstance(result, MappingError)

    def test_non_dict_input_is_mapping_error_not_a_raise(self) -> None:
        result = map_payment(["not", "a", "dict"])

        assert isinstance(result, MappingError)

    def test_unparseable_amount_is_mapping_error_not_a_raise(self) -> None:
        """`Decimal(str("N/A"))` raises `decimal.InvalidOperation`, which
        IS an `ArithmeticError` but NOT a `ValueError`. Omitting
        `ArithmeticError` from the except clause would let this escape
        and crash the sweep on a single bad payment."""
        raw = _raw_payment(net_received_amount="N/A")
        result = map_payment(raw)

        assert isinstance(result, MappingError)

    def test_unparseable_charge_amount_is_mapping_error_not_a_raise(self) -> None:
        raw = _raw_payment(charges_details=[{"name": "fee", "type": "fee", "amount": "garbage"}])
        result = map_payment(raw)

        assert isinstance(result, MappingError)

    def test_non_list_charges_details_is_mapping_error(self) -> None:
        raw = _raw_payment(charges_details={"not": "a list"})
        result = map_payment(raw)

        assert isinstance(result, MappingError)
