"""RED/GREEN -- the shipping a Flex buyer pays to us when the payment does not
carry it (flex-envio-comprador).

Order 2000018999267608: the payment's `shipping_amount` is 0, yet the ML panel
shows "Cargo por Envíos de Mercado Libre (a cargo del comprador)" +5990 and
the shipment's `raw_costs.receiver.cost_details` holds `{amount: 5990,
sender_id: <us>}`. The rule, in order:

1. a relevant payment of the shipment carries `shipping_amount > 0` -> that,
   exactly as before;
2. otherwise, on `self_service` only, Σ `receiver.cost_details[].amount`
   toward the seller, split to the cent across the orders of the shipment.

Every `raw_costs` is a REAL capture (`_flex_receiver_capture`,
`_envio_comprador_capture`).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.ml_ventas_desglose.breakdown_service import (
    compute_breakdown,
    compute_neto_by_order_ids,
    compute_neto_desglose_by_order_ids,
)
from app.services.ml_ventas_desglose.envio_comprador import resolve_envio_comprador_flex_by_order_ids
from app.services.ml_ventas_desglose.iva import CONCEPTO_ENVIO_COMPRADOR, IVA_ML_DIVISOR, descomponer_neto
from app.services.order_metrics import constants
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION

from ._envio_comprador_capture import SELF_SERVICE_4990, SELF_SERVICE_PACK, seed_case
from ._flex_receiver_capture import ORDER_5990, SHIPMENT_5990, raw_costs, seed_order_5990

D = Decimal


def _envio_components(desc):
    return [c for c in desc.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR]


class TestTheReportedSale:
    """Order 2000018999267608: payment shipping 0, `cost_details` 5990."""

    def test_the_buyer_shipping_component_is_5990_outside_the_payment(self, db) -> None:
        seed_order_5990(db)

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]

        [componente] = _envio_components(desc)
        assert (componente.bruto, componente.base, componente.iva) == (D("5990"), D("4950.41"), D("1039.59"))
        assert componente.alicuota == D("21")
        assert componente.fuera_del_pago is True
        assert (desc.envio_comprador.bruto, desc.envio_comprador.neto) == (D("5990"), D("4950.41"))

    def test_the_payment_reconciliation_does_not_see_it(self, db) -> None:
        """Payment side: 9044 against the goods line 14000 (the fee and taxes
        charges are not seeded). MUTATION: `fuera_del_pago=False` folds 5990
        into the payment sum and moves this to -10946."""
        seed_order_5990(db)

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]

        assert desc.diferencia == D("9044") - D("14000")

    def test_the_neto_includes_the_5990_on_every_path(self, db) -> None:
        seed_order_5990(db)

        listing = compute_neto_by_order_ids(db, [ORDER_5990])[ORDER_5990]
        breakdown = compute_breakdown(db, [ORDER_5990])

        assert listing == breakdown.neto == D("9044") + D("5990")
        line = next(line for line in breakdown.lines if line.concepto == CONCEPTO_ENVIO_COMPRADOR)
        assert (line.monto, line.origen) == (D("-5990"), "envio_comprador")

    def test_the_tooltip_identity_still_holds(self, db) -> None:
        """`neto == neto_depositado + retenciones + bonificación` -- the 5990 is
        money ML collects for us in the same operation, so it is deposited."""
        seed_order_5990(db)

        breakdown = compute_breakdown(db, [ORDER_5990])
        depositado, retenciones = compute_neto_desglose_by_order_ids(db, [ORDER_5990])[ORDER_5990]

        assert breakdown.neto_depositado == depositado == D("15034")
        assert breakdown.neto == depositado + retenciones + breakdown.bonificacion_envio

    def test_it_enters_the_varios_base_without_iva(self, db) -> None:
        seed_order_5990(db)

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]

        assert desc.base_venta_sin_iva == D("11570.25")  # 14000 / 1.21
        assert desc.base_varios == D("11570.25") + D("4950.41")

    def test_the_stored_metrics_carry_it(self, db) -> None:
        seed_order_5990(db)

        metrics = compute_order_metrics(db, [ORDER_5990])[ORDER_5990]

        assert metrics.neto == D("15034")


class TestCountedOnce:
    def test_the_payment_amount_wins_when_both_exist(self, db) -> None:
        """The payment carries 5990 AND `cost_details` says 5990: one line,
        inside the payment. MUTATION: dropping the "a payment carries it"
        guard adds a second 5990."""
        seed_order_5990(db, shipping_amount=5990.0, net_received_amount=15034.0)

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]
        neto = compute_neto_by_order_ids(db, [ORDER_5990])[ORDER_5990]

        [componente] = _envio_components(desc)
        assert componente.fuera_del_pago is False
        assert componente.bruto == D("5990")
        assert neto == D("15034")
        assert resolve_envio_comprador_flex_by_order_ids(db, [ORDER_5990], IVA_ML_DIVISOR) == {}

    def test_the_captured_4990_sale_is_unchanged(self, db) -> None:
        """Captured self_service sale: payment 4990 and `cost_details` 4990."""
        seed_case(db, SELF_SERVICE_4990)

        desc = descomponer_neto(db, [SELF_SERVICE_4990])[SELF_SERVICE_4990]

        assert [c.bruto for c in _envio_components(desc)] == [D("4990")]
        assert compute_neto_by_order_ids(db, [SELF_SERVICE_4990])[SELF_SERVICE_4990] == D("15879.46")


class TestOnlyFlex:
    def test_cross_docking_with_cost_details_is_not_counted(self, db) -> None:
        """Cross-docking takes the buyer's shipping back with a `shp_*`
        charge. MUTATION: dropping the `self_service` guard counts 5990."""
        seed_order_5990(db, logistic_type="cross_docking")

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]

        assert _envio_components(desc) == []
        assert desc.envio_comprador is None
        assert compute_neto_by_order_ids(db, [ORDER_5990])[ORDER_5990] == D("9044")


class TestOnlyTowardTheSeller:
    def test_an_entry_toward_another_sender_is_ignored(self, db) -> None:
        """MUTATION: dropping the `sender_id` filter counts 5990."""
        costs = raw_costs(SHIPMENT_5990)
        costs["receiver"]["cost_details"][0]["sender_id"] += 1
        seed_order_5990(db, costs=costs)

        desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]

        assert _envio_components(desc) == []
        assert compute_neto_by_order_ids(db, [ORDER_5990])[ORDER_5990] == D("9044")


class TestTheCapturedFlexPack:
    """Pack 2000015400388457: payment shipping 0, `cost_details` 2216.30 (the
    ML panel shows "Cargo por Envíos ... (a cargo del comprador) $2.216,30")."""

    SIBLING = SELF_SERVICE_PACK + 1

    def _seed_two_order_pack(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK)
        seed_case(db, SELF_SERVICE_PACK, order_id=self.SIBLING, with_shipment=False)

    def test_a_single_order_pack_gets_the_whole_2216_30(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK)

        desc = descomponer_neto(db, [SELF_SERVICE_PACK])[SELF_SERVICE_PACK]

        assert (desc.envio_comprador.bruto, desc.envio_comprador.neto) == (D("2216.30"), D("1831.65"))

    def test_two_orders_split_it_to_the_cent(self, db) -> None:
        """2216.30 -> 1108.15 + 1108.15; 1831.65 -> 915.83 + 915.82 (the extra
        cent to the lowest order_id). MUTATION: giving each order the whole
        amount fails the sums."""
        self._seed_two_order_pack(db)
        ids = [SELF_SERVICE_PACK, self.SIBLING]

        shares = resolve_envio_comprador_flex_by_order_ids(db, ids, IVA_ML_DIVISOR)

        assert [(shares[i].bruto, shares[i].neto) for i in ids] == [
            (D("1108.15"), D("915.83")),
            (D("1108.15"), D("915.82")),
        ]
        descs = descomponer_neto(db, ids)
        assert sum(descs[i].envio_comprador.bruto for i in ids) == D("2216.30")
        assert sum(descs[i].envio_comprador.neto for i in ids) == D("1831.65")

    def test_the_pack_neto_counts_it_once(self, db) -> None:
        self._seed_two_order_pack(db)
        ids = [SELF_SERVICE_PACK, self.SIBLING]

        breakdown = compute_breakdown(db, ids)
        listing = compute_neto_by_order_ids(db, ids)

        line = next(line for line in breakdown.lines if line.concepto == CONCEPTO_ENVIO_COMPRADOR)
        assert line.monto == D("-2216.30")
        assert breakdown.neto == sum(listing.values())


class TestTheRecompute:
    def test_the_formula_version_is_bumped_and_documented(self) -> None:
        """The bump is what makes `order_metrics.reconcile` recompute every
        stored sale (and its sale lines) with the new neto."""
        assert CURRENT_FORMULA_VERSION == 8
        assert "- 8: flex-envio-comprador" in constants.__doc__
