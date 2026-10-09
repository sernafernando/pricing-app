"""ml-billing-balance PR 5-i -- flex rows: mapper and storage (tasks 5.3, 5.5, BF-2, BF-5).

The rows are real: `flex_rows.json` copies the captured flex details verbatim
(README names the sources). Flex rows have NO `items_info`; the order they
belong to is `shipping_info.order.order_id`. BFLX is the explicit Flex shipping
bonification: order 2000018846584294 -> 599, order 2000018808335864 -> 8,990.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.services.ml_billing.billing_sweep_service import persist_details_page
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO, MappingError, map_billing_detail

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_ROWS = json.loads((_FIXTURES / "flex_rows.json").read_text())
_GENERAL_ROW = json.loads((_FIXTURES / "general_bill_2026_09_01_sample_rows.json").read_text())["rows"][0]


def _flex(name: str) -> BillingChargeDTO:
    entry = _ROWS[name]
    dto = map_billing_detail(entry["row"], entry["period"], entry["document_type"], billing_source="flex")
    assert isinstance(dto, BillingChargeDTO)
    return dto


class TestFlexMapper:
    def test_bflx_599_links_its_order_through_shipping_info(self) -> None:
        dto = _flex("bflx_599")
        assert dto.billing_source == "flex"
        assert (dto.detail_sub_type, dto.detail_type, dto.document_type) == ("BFLX", "BONUS", "CREDIT_NOTE")
        assert dto.amount == Decimal("-599.0")  # BONUS is stored negated, like every credit note
        assert dto.order_ids == [2000018846584294]
        assert dto.legal_document_number is None and dto.legal_document_status == "PROCESSING"

    def test_bflx_8990_links_its_order(self) -> None:
        dto = _flex("bflx_8990")
        assert (dto.amount, dto.order_ids) == (Decimal("-8990.0"), [2000018808335864])

    def test_the_whole_row_is_kept(self) -> None:
        entry = _ROWS["bflx_599"]
        assert _flex("bflx_599").raw_detail == entry["row"]  # receiver_nickname, buyer_nickname and all

    def test_cflx_and_bflx_keep_their_reciprocal_links(self) -> None:
        charge, bonus = _flex("cflx_reciprocal"), _flex("bflx_reciprocal")
        assert charge.raw_detail["charge_info"]["detail_associated_id"] == int(bonus.detail_id)
        assert bonus.raw_detail["charge_info"]["detail_associated_id"] == int(charge.detail_id)
        assert (charge.amount, bonus.amount) == (Decimal("649.0"), Decimal("-649.0"))
        assert charge.order_ids == bonus.order_ids == [2000017977526962]

    def test_an_order_in_items_info_and_in_shipping_info_is_linked_once(self) -> None:
        # No captured flex row has `items_info` (0 of 13,688); this derives one
        # from a captured row to pin the dedup rule, nothing more.
        raw = copy.deepcopy(_ROWS["bflx_599"]["row"])
        raw["items_info"] = [{"order_id": 2000018846584294}, {"order_id": 2000000000000001}]
        dto = map_billing_detail(raw, "2026-10-01", "CREDIT_NOTE", billing_source="flex")
        assert dto.order_ids == [2000018846584294, 2000000000000001]

    def test_a_flex_row_without_an_order_has_no_links(self) -> None:
        raw = copy.deepcopy(_ROWS["bflx_599"]["row"])
        raw["shipping_info"].pop("order")
        assert map_billing_detail(raw, "2026-10-01", "CREDIT_NOTE", billing_source="flex").order_ids == []

    def test_a_general_row_is_untouched(self) -> None:
        dto = map_billing_detail(_GENERAL_ROW, "2026-09-01")
        assert dto.billing_source == "general"
        assert dto.order_ids == [int(_GENERAL_ROW["items_info"][0]["order_id"])]

    def test_an_unknown_source_is_a_mapping_error(self) -> None:
        result = map_billing_detail(_ROWS["bflx_599"]["row"], "2026-10-01", "CREDIT_NOTE", billing_source="flexx")
        assert isinstance(result, MappingError) and "billing_source" in result.reason

    def test_the_general_mapper_ignores_shipping_info_orders(self) -> None:
        raw = copy.deepcopy(_ROWS["bflx_599"]["row"])
        assert map_billing_detail(raw, "2026-10-01", "CREDIT_NOTE").order_ids == []  # default source is general


class TestFlexStorage:
    def test_a_flex_row_is_stored_with_its_source_and_order_link(self, db) -> None:
        upsert_billing_charge(db, _flex("bflx_599"))
        db.commit()
        charge = db.query(MlBillingCharge).one()
        assert (charge.billing_source, charge.detail_sub_type, charge.amount) == ("flex", "BFLX", Decimal("-599.00"))
        assert [link.order_id for link in db.query(MlBillingChargeOrder).all()] == [2000018846584294]

    def test_refetching_is_idempotent(self, db) -> None:
        for _ in range(2):
            upsert_billing_charge(db, _flex("bflx_8990"))
            db.commit()
        assert db.query(MlBillingCharge).count() == 1
        assert db.query(MlBillingChargeOrder).count() == 1

    def test_flex_rows_are_additive_to_general_rows(self, db) -> None:
        general = map_billing_detail(_GENERAL_ROW, "2026-09-01")
        upsert_billing_charge(db, general)
        upsert_billing_charge(db, _flex("bflx_599"))
        db.commit()
        sources = {c.detail_id: c.billing_source for c in db.query(MlBillingCharge).all()}
        assert sources == {general.detail_id: "general", "72841878795": "flex"}

    def test_a_flex_fetch_never_relabels_an_existing_general_row(self, db) -> None:
        general = _flex("bflx_599")
        upsert_billing_charge(db, BillingChargeDTO(**{**general.__dict__, "billing_source": "general"}))
        upsert_billing_charge(db, general)
        db.commit()
        assert db.query(MlBillingCharge).one().billing_source == "general"

    def test_persist_details_page_stores_a_flex_page(self, db) -> None:
        rows = [_ROWS["bflx_599"]["row"], _ROWS["bflx_8990"]["row"]]
        assert persist_details_page(db, rows, "2026-10-01", "CREDIT_NOTE", billing_source="flex") == (2, 2, 0)
        db.commit()
        assert {c.billing_source for c in db.query(MlBillingCharge).all()} == {"flex"}
        assert db.query(MlBillingChargeOrder).count() == 2
