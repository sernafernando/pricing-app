"""RED/GREEN -- the Flex "Bonificación por envío" (ventas-ml-bonificacion-envio-flex).

On a Flex sale whose buyer got free shipping through an ML discount, ML pays
the seller for the shipping the seller delivers. That money sits in
`ml_shipments_ops.raw_costs` (`receiver.discounts[].promoted_amount`), not in
the payment net. Every fixture here comes from a REAL capture
(`_bonificacion_capture.py`): the confirmed figure for sale 2000018808335864
is $8.990 with IVA, i.e. $7.429,75 without.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from app.models.ml_orders_ops import MlShipmentOps
from app.services.ml_ventas_desglose import bonificacion_flex
from app.services.ml_ventas_desglose.bonificacion_flex import (
    bonificacion_bruta_desde_raw_costs,
    repartir_en_centavos,
    resolve_bonificacion_flex_by_order_ids,
)
from app.services.ml_ventas_desglose.deducciones import (
    DEDUCCIONES,
    BonificacionEnvioDeduccion,
    calcular_total_gauss,
)
from app.services.ml_ventas_desglose.iva import IVA_ML_DIVISOR, descomponer_neto
from app.services.order_metrics.compute import compute_order_metrics

from ._bonificacion_capture import (
    GROSS,
    NET_OF_IVA,
    ORDER_ID,
    SHIPMENT_ID,
    capture,
    seed_capture,
)
from ._envio_comprador_capture import SELF_SERVICE_PACK, seed_case

CAPTURED_RAW_COSTS = capture()["db"]["shipments"][0]["raw_costs"]


def _raw_costs_with(discounts, sender_discounts=None):
    payload = {**CAPTURED_RAW_COSTS, "receiver": {**CAPTURED_RAW_COSTS["receiver"], "discounts": discounts}}
    if sender_discounts is not None:
        payload["senders"] = [{**CAPTURED_RAW_COSTS["senders"][0], "discounts": sender_discounts}]
    return payload


class TestParsingTheCapturedPayload:
    def test_the_real_capture_is_the_confirmed_8990(self) -> None:
        assert bonificacion_bruta_desde_raw_costs(CAPTURED_RAW_COSTS, SHIPMENT_ID) == GROSS

    def test_the_amount_is_the_sum_of_every_loyal_promoted_amount(self) -> None:
        raw = _raw_costs_with(
            [
                {"rate": 1, "type": "loyal", "promoted_amount": 3000},
                {"rate": 1, "type": "loyal", "promoted_amount": 5990},
            ]
        )
        assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) == Decimal("8990")

    def test_the_sellers_own_discounts_are_the_bonificacion(self) -> None:
        """The ML panel's "Bonificación por envío" of pack 2000015400388457 is
        $599 = `senders[0].discounts[mandatory].promoted_amount`, not the
        buyer's `ratio` subsidy. The sender sum and the loyal sum add up."""
        raw = _raw_costs_with(
            [{"rate": 1, "type": "loyal", "promoted_amount": 100}],
            sender_discounts=[
                {"rate": 0.1, "type": "mandatory", "promoted_amount": 599},
                {"rate": 0.1, "type": "mandatory", "promoted_amount": 1},
            ],
        )
        assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) == Decimal("700")

    def test_the_buyers_ratio_subsidy_is_not_income(self, caplog) -> None:
        """MUTATION: summing every `receiver.discounts` (the #1415 rule)
        turns the captured pack's 599 into 3773.7. `ratio` is ML's subsidy to
        the buyer; it is known, so it adds nothing and it is silent."""
        raw = _raw_costs_with([{"rate": 0.63, "type": "ratio", "promoted_amount": 3773.7}], sender_discounts=[])
        with caplog.at_level(logging.WARNING, logger=bonificacion_flex.__name__):
            assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None
        assert caplog.text == ""

    def test_an_unknown_receiver_discount_type_adds_nothing_and_logs(self, caplog) -> None:
        """Fail-closed: a type nobody has seen is never assumed to be income.
        Only that entry is skipped; the loyal one next to it still counts."""
        raw = _raw_costs_with(
            [
                {"rate": 1, "type": "brand_new", "promoted_amount": 5000},
                {"rate": 1, "type": "loyal", "promoted_amount": 8990},
            ]
        )
        with caplog.at_level(logging.WARNING, logger=bonificacion_flex.__name__):
            assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) == Decimal("8990")
        assert "brand_new" in caplog.text
        assert "48178052704" in caplog.text

    def test_a_discount_without_a_type_adds_nothing_and_logs(self, caplog) -> None:
        raw = _raw_costs_with([{"rate": 1, "promoted_amount": 8990}])
        with caplog.at_level(logging.WARNING, logger=bonificacion_flex.__name__):
            assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None
        assert "48178052704" in caplog.text

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            {},
            [],
            "x",
            {"receiver": None},
            {"receiver": []},
            {"receiver": {}},
            {"receiver": {"discounts": None}},
            {"receiver": {"discounts": {}}},
            {"receiver": {"discounts": []}},
            {"receiver": {"discounts": [{"rate": 1, "type": "loyal", "promoted_amount": 0}]}},
        ],
    )
    def test_nothing_to_pay_is_nothing(self, raw) -> None:
        assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None

    @pytest.mark.parametrize(
        "bad",
        [None, "8990", "abc", -1, -8990.5, True, False, float("nan"), float("inf"), [8990], {"v": 1}],
        ids=repr,
    )
    def test_a_missing_non_numeric_or_negative_amount_never_adds_money(self, bad, caplog) -> None:
        entry = {"rate": 1, "type": "loyal"} if bad is None else {"rate": 1, "type": "loyal", "promoted_amount": bad}
        with caplog.at_level(logging.WARNING, logger=bonificacion_flex.__name__):
            assert bonificacion_bruta_desde_raw_costs(_raw_costs_with([entry]), SHIPMENT_ID) is None
        assert "48178052704" in caplog.text

    def test_one_bad_entry_poisons_the_whole_shipment_not_just_itself(self) -> None:
        """When in doubt, nothing: a valid 5990 next to an unreadable entry
        would pay an amount we cannot show adds up to what ML paid."""
        raw = _raw_costs_with([{"rate": 1, "type": "loyal", "promoted_amount": 5990}, {"rate": 1, "type": "loyal"}])
        assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None

    def test_an_unreadable_sender_discount_poisons_the_whole_shipment_too(self) -> None:
        raw = _raw_costs_with(
            [{"rate": 1, "type": "loyal", "promoted_amount": 5990}],
            sender_discounts=[{"rate": 0.1, "type": "mandatory", "promoted_amount": "599"}],
        )
        assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None

    def test_senders_that_are_not_a_list_of_objects_are_nothing_and_logged(self, caplog) -> None:
        for senders in ("x", {}, ["x"], [{"discounts": "x"}]):
            raw = {**CAPTURED_RAW_COSTS, "senders": senders}
            with caplog.at_level(logging.WARNING, logger=bonificacion_flex.__name__):
                assert bonificacion_bruta_desde_raw_costs(raw, SHIPMENT_ID) is None
            assert "48178052704" in caplog.text
            caplog.clear()

    def test_a_malformed_entry_that_is_not_an_object_is_nothing(self) -> None:
        assert bonificacion_bruta_desde_raw_costs(_raw_costs_with(["8990"]), SHIPMENT_ID) is None


class TestTheCapturedFlexPackIsTheSellersOwnDiscount:
    """Pack 2000015400388457 (order 2000018846584294), checked against the ML
    panel: Envíos $1.826,30 = cargo al comprador $2.216,30 - Cargo Flex $390,
    and "Bonificación por envío" $599. The panel's $599 is
    `senders[0].discounts[mandatory]`; the buyer's `ratio` 3773.7 is ML's
    subsidy to the buyer and never the seller's income."""

    def test_the_resolver_gives_599_not_the_buyers_subsidy(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK)

        share = resolve_bonificacion_flex_by_order_ids(db, [SELF_SERVICE_PACK], IVA_ML_DIVISOR)[SELF_SERVICE_PACK]

        assert (share.bruto, share.neto) == (Decimal("599"), Decimal("495.04"))

    def test_the_chain_line_is_the_599_net_of_iva(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK)

        assert BonificacionEnvioDeduccion().resolve_bulk(db, [SELF_SERVICE_PACK]) == {
            SELF_SERVICE_PACK: Decimal("-495.04")
        }


class TestExactCentSplit:
    @pytest.mark.parametrize(
        "total,n", [("7429.75", 1), ("7429.75", 2), ("7429.75", 3), ("0.01", 3), ("8990", 7), ("1.00", 4)]
    )
    def test_the_shares_always_add_up_to_the_total_exactly(self, total, n) -> None:
        shares = repartir_en_centavos(Decimal(total), n)
        assert len(shares) == n
        assert sum(shares) == Decimal(total)
        assert max(shares) - min(shares) <= Decimal("0.01")
        assert shares == sorted(shares, reverse=True)  # the remainder goes first


class TestResolverOverTheCapture:
    def test_a_flex_order_gets_gross_and_net_of_iva(self, db) -> None:
        seed_capture(db)

        result = resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID], IVA_ML_DIVISOR)

        assert result[ORDER_ID].bruto == GROSS
        assert result[ORDER_ID].neto == NET_OF_IVA

    def test_a_non_flex_order_with_the_same_discounts_adds_nothing(self, db) -> None:
        """ML subsidises the buyer's discount on drop-off/fulfillment; it is
        not income for the seller. MUTATION: dropping the self_service gate
        must fail this test."""
        seed_capture(db, logistic_type="cross_docking")

        assert resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID], IVA_ML_DIVISOR) == {}
        assert BonificacionEnvioDeduccion().resolve_bulk(db, [ORDER_ID]) == {}

    def test_an_order_without_a_synced_shipment_cost_adds_nothing_and_does_not_block(self, db) -> None:
        seed_capture(db, raw_costs=None)

        assert resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID], IVA_ML_DIVISOR) == {}

    def test_a_pack_shares_one_shipment_so_the_bonificacion_is_counted_once(self, db) -> None:
        """Three orders, one shipment, one bonificacion. Each order gets a
        share and the shares add up to the shipment's amount EXACTLY -- in
        gross and in net. MUTATION: giving every order the whole amount
        triples it."""
        sibling_a, sibling_b = ORDER_ID + 1, ORDER_ID + 2
        seed_capture(db)
        seed_capture(db, order_id=sibling_a, seed_shared_rows=False)
        seed_capture(db, order_id=sibling_b, seed_shared_rows=False)

        result = resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID, sibling_a, sibling_b], IVA_ML_DIVISOR)

        assert sum(r.bruto for r in result.values()) == GROSS
        assert sum(r.neto for r in result.values()) == NET_OF_IVA
        assert all(r.bruto < GROSS for r in result.values())

    def test_an_order_share_does_not_depend_on_who_else_is_in_the_batch(self, db) -> None:
        """The divisor comes from the database, never from `order_ids`:
        otherwise a number changes when you scroll."""
        sibling = ORDER_ID + 1
        seed_capture(db)
        seed_capture(db, order_id=sibling, seed_shared_rows=False)

        alone = resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID], IVA_ML_DIVISOR)
        together = resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID, sibling], IVA_ML_DIVISOR)

        assert alone[ORDER_ID] == together[ORDER_ID]

    def test_the_net_matches_the_split_iva_py_applies_to_every_ml_figure(self, db) -> None:
        from app.services.ml_ventas_desglose.iva import _split

        seed_capture(db)
        base, _iva = _split(GROSS, IVA_ML_DIVISOR)

        assert resolve_bonificacion_flex_by_order_ids(db, [ORDER_ID], IVA_ML_DIVISOR)[ORDER_ID].neto == base


class TestInTheChain:
    def test_the_deduction_is_registered_and_negative_so_it_adds(self, db) -> None:
        seed_capture(db)
        assert BonificacionEnvioDeduccion.code in [d.code for d in DEDUCCIONES]

        assert BonificacionEnvioDeduccion().resolve_bulk(db, [ORDER_ID]) == {ORDER_ID: -NET_OF_IVA}

    def test_total_gauss_rises_by_exactly_the_net_bonificacion(self, db) -> None:
        """The reported bug: same sale, with and without the captured
        discount. MUTATION: leaving the deduction out of DEDUCCIONES fails
        this."""
        seed_capture(db)
        with_bonus = compute_order_metrics(db, [ORDER_ID])[ORDER_ID]

        shipment = db.query(MlShipmentOps).filter_by(shipment_id=SHIPMENT_ID).one()
        shipment.raw_costs = _raw_costs_with([])
        db.commit()
        without_bonus = compute_order_metrics(db, [ORDER_ID])[ORDER_ID]

        assert without_bonus.total_gauss is not None
        assert with_bonus.total_gauss - without_bonus.total_gauss == NET_OF_IVA
        codes = [code for code, _m, _c in with_bonus.lineas]
        assert "bonificacion_envio" in codes
        assert "bonificacion_envio" not in [code for code, _m, _c in without_bonus.lineas]
        line = next(l for l in with_bonus.lineas if l[0] == "bonificacion_envio")
        assert line[1] == -NET_OF_IVA

    def test_it_is_stored_and_read_back_with_its_label(self, db) -> None:
        from app.services.order_metrics.read import read_stored_metrics
        from app.services.order_metrics.store import recompute_order_metrics

        seed_capture(db)
        recompute_order_metrics(db, [ORDER_ID])
        db.commit()

        stored = read_stored_metrics(db, [ORDER_ID])[ORDER_ID]

        line = next(l for l in stored.lineas if l[0] == "bonificacion_envio")
        assert line[1] == -NET_OF_IVA
        assert line[2] == "Bonificación por envío"

    def test_a_pack_does_not_duplicate_it_in_the_orders_total_gauss(self, db) -> None:
        sibling = ORDER_ID + 1
        seed_capture(db)
        seed_capture(db, order_id=sibling, seed_shared_rows=False)
        both = compute_order_metrics(db, [ORDER_ID, sibling])

        shipment = db.query(MlShipmentOps).filter_by(shipment_id=SHIPMENT_ID).one()
        shipment.raw_costs = _raw_costs_with([])
        db.commit()
        none = compute_order_metrics(db, [ORDER_ID, sibling])

        gained = sum(both[o].total_gauss - none[o].total_gauss for o in (ORDER_ID, sibling))
        assert gained == NET_OF_IVA

    def test_the_chain_unit_adds_the_negative_monto(self, db) -> None:
        seed_capture(db)
        result = calcular_total_gauss(
            db, [ORDER_ID], {ORDER_ID: Decimal("1000.00")}, base_varios_by_order={ORDER_ID: Decimal("500")}
        )[ORDER_ID]
        monto = next(m for code, m, _c in result.lineas if code == "bonificacion_envio")
        assert monto == -NET_OF_IVA


class TestIvaDecomposition:
    def test_it_shows_as_an_informative_21_percent_component(self, db) -> None:
        seed_capture(db)

        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]

        componente = next(c for c in desc.componentes if c.concepto == "Bonificación por envío")
        assert componente.informativo is True
        assert componente.alicuota == Decimal("21")
        assert (componente.bruto, componente.base, componente.iva) == (GROSS, NET_OF_IVA, Decimal("1560.25"))

    def test_it_does_not_break_the_exact_reconciliation_nor_move_neto_sin_iva(self, db) -> None:
        """It is NOT inside `net_received_amount`, so counting it in the
        reconciliation would break D12's exact equality."""
        seed_capture(db)
        with_bonus = descomponer_neto(db, [ORDER_ID])[ORDER_ID]

        shipment = db.query(MlShipmentOps).filter_by(shipment_id=SHIPMENT_ID).one()
        shipment.raw_costs = _raw_costs_with([])
        db.commit()
        without_bonus = descomponer_neto(db, [ORDER_ID])[ORDER_ID]

        assert with_bonus.reconcilia is True
        assert with_bonus.neto_sin_iva is not None
        assert with_bonus.neto_sin_iva == without_bonus.neto_sin_iva
        assert with_bonus.diferencia == without_bonus.diferencia == Decimal("0")
