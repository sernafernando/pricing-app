"""
RED/GREEN — `map_billing_detail` (ml-ventas-desglose-costos, corte 2).

Spec coverage:
  REQ-1 — sign: `detail_type == "BONUS"` -> amount is NEGATIVE.
          `detail_type == "CHARGE"` -> amount is POSITIVE. All amounts
          arrive positive from ML (investigation §6/§5.b) -- the mapper
          is the ONLY place that applies a sign.
  REQ-2 — the sign is decided by `detail_type`, a real field, NEVER by a
          string-prefix heuristic on `detail_sub_type` (a sub_type
          starting with "B" but `detail_type == "CHARGE"` stays POSITIVE).
  REQ-3 (PII) — `sales_info[].payer_nickname` / `sales_info[].state_name`
          are discarded before `raw_detail` is built; neither key/value
          may appear anywhere in the resulting `raw_detail`.
  REQ-4 — `order_ids` is the deduped list of `items_info[].order_id`,
          coerced to `int` (BigInteger-range safe).
"""

from __future__ import annotations

from app.services.ml_billing_ingestion.mapper import BillingChargeDTO, MappingError, map_billing_detail


def _raw_detail(**overrides):
    base = {
        "charge_info": {
            "detail_id": "12345",
            "detail_type": "CHARGE",
            "detail_sub_type": "CVFV",
            "detail_amount": 91250,
            "transaction_detail": "Cargo por vender",
            "creation_date_time": "2026-09-01T10:00:00.000-04:00",
        },
        "items_info": [{"order_id": 2000018265495500, "item_id": "MLA123"}],
        "sales_info": [
            {
                "order_id": 2000018265495500,
                "operation_id": "OP1",
                "payer_nickname": "SECRETO123",
                "state_name": "Buenos Aires",
            }
        ],
        "shipping_info": {},
        "discount_info": {},
        "document_info": {"document_id": "DOC1"},
    }
    base.update(overrides)
    return base


class TestSign:
    def test_charge_is_positive(self) -> None:
        raw = _raw_detail()
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == 91250.0

    def test_bonus_is_negative(self) -> None:
        raw = _raw_detail()
        raw["charge_info"]["detail_type"] = "BONUS"
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == -91250.0

    def test_sub_type_b_prefix_with_charge_type_stays_positive(self) -> None:
        """`detail_sub_type` starting with "B" (e.g. a real ML reversal code
        like BVFV) is NOT the sign rule. Only `detail_type` decides."""
        raw = _raw_detail()
        raw["charge_info"]["detail_sub_type"] = "BVFV"
        raw["charge_info"]["detail_type"] = "CHARGE"
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == 91250.0


class TestPii:
    def test_payer_nickname_and_state_name_are_stripped(self) -> None:
        raw = _raw_detail()
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        serialized = str(result.raw_detail)
        assert "SECRETO123" not in serialized
        assert "payer_nickname" not in serialized
        assert "Buenos Aires" not in serialized
        assert "state_name" not in serialized
        # everything else in sales_info survives
        assert "OP1" in serialized


class TestOrderIds:
    def test_order_ids_from_items_info_deduped(self) -> None:
        raw = _raw_detail()
        raw["items_info"] = [
            {"order_id": 2000018265495500, "item_id": "MLA1"},
            {"order_id": 2000018265495500, "item_id": "MLA2"},
            {"order_id": 2000018265495501, "item_id": "MLA3"},
        ]
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.order_ids == [2000018265495500, 2000018265495501]


class TestMappingError:
    def test_missing_detail_id_is_mapping_error(self) -> None:
        raw = _raw_detail()
        del raw["charge_info"]["detail_id"]
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, MappingError)
