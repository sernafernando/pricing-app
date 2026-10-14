"""ml-billing-balance PR 9-i -- the Flex bonification comes from the billing BFLX
line, with `raw_costs` as the fallback until billing arrives (owner decision
2026-10-14, DG-1).

Fixtures are captured: the BFLX rows are `tests/fixtures/ml_billing/flex_rows.json`
(order 2000018846584294 -> 599, order 2000018808335864 -> 8,990) stored through the
real mapper and ingestion, so the stored sign (BONUS negated) is the production one.
Cases marked DERIVED change one field of a captured row to isolate one rule.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
from decimal import Decimal
from pathlib import Path

from app.models.ml_orders_ops import MlShipmentOps
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import BillingChargeDTO, map_billing_detail
from app.services.ml_ventas_desglose.bonificacion_flex import resolve_bonificacion_flex_by_order_ids
from app.services.ml_ventas_desglose.iva import IVA_ML_DIVISOR
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION

from ._bonificacion_capture import GROSS, NET_OF_IVA, ORDER_ID, SHIPMENT_ID, seed_capture
from ._envio_comprador_capture import SELF_SERVICE_PACK, seed_case

_ROWS = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing" / "flex_rows.json").read_text())
_SENDER_599_NET = Decimal("495.04")


def _store(db, name: str, **changes) -> BillingChargeDTO:
    entry = copy.deepcopy(_ROWS[name])
    dto = map_billing_detail(entry["row"], entry["period"], entry["document_type"], billing_source="flex")
    assert isinstance(dto, BillingChargeDTO)
    dto = dataclasses.replace(dto, **changes)
    upsert_billing_charge(db, dto)
    db.commit()
    return dto


def _resolve(db, order_ids):
    return resolve_bonificacion_flex_by_order_ids(db, order_ids, IVA_ML_DIVISOR)


class TestBflxIsTheSourceWhenItExists:
    def test_bflx_8990_is_used_even_without_a_cost_payload(self, db) -> None:
        """Billing alone, no `raw_costs` at all: the figure comes from BFLX."""
        seed_capture(db, raw_costs=None)
        _store(db, "bflx_8990")

        share = _resolve(db, [ORDER_ID])[ORDER_ID]

        assert (share.bruto, share.neto) == (GROSS, NET_OF_IVA)

    def test_bflx_599_is_used_even_without_a_cost_payload(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK, raw_costs=None)
        _store(db, "bflx_599")

        share = _resolve(db, [SELF_SERVICE_PACK])[SELF_SERVICE_PACK]

        assert (share.bruto, share.neto) == (Decimal("599"), _SENDER_599_NET)

    def test_both_sources_agree_on_the_captured_orders_so_no_money_moves(self, db) -> None:
        """Order 2000018808335864 with its captured `raw_costs` (loyal 8,990)."""
        seed_capture(db)
        before = _resolve(db, [ORDER_ID])
        _store(db, "bflx_8990")

        assert _resolve(db, [ORDER_ID]) == before

    def test_billing_wins_when_the_two_sources_disagree(self, db) -> None:
        """DERIVED: the captured `raw_costs` altered to 1,000 (the real one is 8,990)."""
        raw_costs = copy.deepcopy(seed_capture(db)["shipments"][0]["raw_costs"])
        raw_costs["receiver"]["discounts"][0]["promoted_amount"] = 1000
        db.query(MlShipmentOps).filter_by(shipment_id=SHIPMENT_ID).update({"raw_costs": raw_costs})
        db.commit()
        _store(db, "bflx_8990")

        assert _resolve(db, [ORDER_ID])[ORDER_ID].bruto == GROSS

    def test_a_pack_shipment_splits_the_bflx_exactly_among_its_orders(self, db) -> None:
        """DERIVED: a sibling order of the captured shipment (BFLX links only one of them)."""
        sibling = ORDER_ID + 1
        seed_capture(db, raw_costs=None)
        seed_capture(db, order_id=sibling, raw_costs=None, seed_shared_rows=False)
        _store(db, "bflx_8990")

        result = _resolve(db, [ORDER_ID, sibling])

        assert set(result) == {ORDER_ID, sibling}
        assert sum(r.bruto for r in result.values()) == GROSS
        assert sum(r.neto for r in result.values()) == NET_OF_IVA

    def test_bflx_does_not_turn_a_non_flex_order_into_a_flex_one(self, db) -> None:
        seed_capture(db, raw_costs=None, logistic_type="cross_docking")
        _store(db, "bflx_8990")

        assert _resolve(db, [ORDER_ID]) == {}


class TestFallbackWhenBillingHasNotArrived:
    def test_no_bflx_row_keeps_todays_raw_costs_figure(self, db) -> None:
        seed_capture(db)

        share = _resolve(db, [ORDER_ID])[ORDER_ID]

        assert (share.bruto, share.neto) == (GROSS, NET_OF_IVA)

    def test_a_linked_charge_that_is_not_bflx_does_not_count(self, db) -> None:
        """DERIVED: the captured CFLX (649, a charge) linked to the order. Only BFLX is the bonification."""
        seed_capture(db)
        _store(db, "cflx_reciprocal", order_ids=[ORDER_ID])

        assert _resolve(db, [ORDER_ID])[ORDER_ID].bruto == GROSS

    def test_an_unusable_bflx_amount_falls_back_and_logs(self, db, caplog) -> None:
        """DERIVED: a BFLX stored positive (the real ones are negative) is not trusted."""
        seed_capture(db)
        _store(db, "bflx_8990", amount=Decimal("500"))

        with caplog.at_level(logging.WARNING):
            share = _resolve(db, [ORDER_ID])[ORDER_ID]

        assert share.bruto == GROSS
        assert "bflx" in caplog.text.lower()

    def test_no_bflx_and_no_costs_is_still_nothing(self, db) -> None:
        seed_capture(db, raw_costs=None)

        assert _resolve(db, [ORDER_ID]) == {}


def test_the_formula_version_is_bumped_so_reconcile_recomputes_every_order() -> None:
    assert CURRENT_FORMULA_VERSION == 6


def test_the_billing_tables_read_by_a_flex_order_have_an_enqueue_trigger(db) -> None:
    """`compute_order_metrics` reads the billing tables for a Flex order, so the
    read-set guard needs them in `TRIGGERED_TABLES` (their triggers are
    `triggers_billing_flex.py`). The guard context manager is not used because
    a Flex order with a label also reads `usuarios`/`operadores`, which predates
    this change."""
    from sqlalchemy import event

    from app.services.order_metrics.compute import compute_order_metrics
    from app.services.order_metrics.read_set_guard import _TABLE_REF_RE
    from app.services.order_metrics.triggers import TRIGGERED_TABLES

    seed_capture(db, with_flex_label=False)
    _store(db, "bflx_8990")
    seen: set = set()

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        seen.update(m.group(1).lower() for m in _TABLE_REF_RE.finditer(statement))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        compute_order_metrics(db, [ORDER_ID])
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    billing = {"ml_billing_charges", "ml_billing_charge_orders"}
    assert billing <= seen
    assert billing <= TRIGGERED_TABLES
