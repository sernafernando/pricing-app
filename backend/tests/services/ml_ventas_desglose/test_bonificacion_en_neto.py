"""RED/GREEN -- the Flex "Bonificación por envío" is part of ML's NETO, not a
deduction of the Total Gauss chain (ventas-ml-bonificacion-en-neto).

The owner's words: the account was right, but the bonificación "entra por la
operación", so it belongs to the neto de ML. Moving it must change what is
SHOWN (neto, neto_sin_iva, the IVA split) and nothing about the money: the
final Total Gauss of every captured case is pinned to the value `origin/main`
produced BEFORE the move (`BEFORE`, measured on the captured fixtures, never
typed from a guess).

Every fixture is a REAL capture (`_bonificacion_capture`,
`_envio_comprador_capture`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_payments import MlPaymentOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose.bonificacion_flex import resolve_bonificacion_flex_by_order_ids
from app.services.ml_ventas_desglose.breakdown_service import (
    CONCEPTO_BONIFICACION_ENVIO,
    compute_breakdown,
    compute_neto_by_order_ids,
    compute_neto_desglose_by_order_ids,
)
from app.services.ml_ventas_desglose.deducciones import DEDUCCIONES
from app.services.ml_ventas_desglose.iva import IVA_ML_DIVISOR, descomponer_neto
from app.services.order_metrics.compute import compute_order_metrics

from ._bonificacion_capture import GROSS, NET_OF_IVA, ORDER_ID, seed_capture
from ._envio_comprador_capture import (
    CROSS_DOCKING,
    FULFILLMENT_990,
    FULFILLMENT_3990,
    PACK_OTHER_SHIPMENT,
    SELF_SERVICE_4990,
    SELF_SERVICE_PACK,
    THREE_PAYMENTS,
    seed_case,
)

D = Decimal

# (neto, neto_sin_iva, total_gauss) measured on `origin/main` (0d1ad051), where
# the bonificación was a negative deduction of the chain.
BEFORE = {
    ORDER_ID: (D("13081.02"), D("10677.99"), D("11107.74")),
    FULFILLMENT_990: (D("12569.71"), D("10252.01"), D("9252.01")),
    CROSS_DOCKING: (D("38120.07"), D("31070.46"), D("30070.46")),
    FULFILLMENT_3990: (D("29518.99"), D("23931.41"), D("22931.41")),
    SELF_SERVICE_4990: (D("15879.46"), D("12985.59"), D("11985.59")),
    SELF_SERVICE_PACK: (D("88932.33"), D("72751.42"), D("71246.46")),
    THREE_PAYMENTS: (D("19312.11"), D("15661.56"), D("14661.56")),
    PACK_OTHER_SHIPMENT: (D("18264.25"), D("14913.11"), D("13913.11")),
}
# The bonificación each case carries (gross, net of IVA); the others carry none.
BONIFICACION = {
    ORDER_ID: (GROSS, NET_OF_IVA),
    SELF_SERVICE_PACK: (D("599"), D("495.04")),
}


def _seed(db, order_id: int) -> None:
    if order_id == ORDER_ID:
        seed_capture(db)
    else:
        seed_case(db, order_id)


class TestTheCapturedSaleOfTheReport:
    """Order 2000018808335864: the payment's `net_received_amount` is 13024.45;
    the stored neto was 13081.02 because the SIRTAC 56.57 is added back."""

    def test_the_neto_grows_by_the_bonificacion_and_the_total_gauss_does_not_move(self, db) -> None:
        seed_capture(db)

        metrics = compute_order_metrics(db, [ORDER_ID])[ORDER_ID]

        assert metrics.neto == D("13081.02") + GROSS  # 22071.02
        assert metrics.neto_sin_iva == D("10677.99") + NET_OF_IVA  # 18107.74
        assert metrics.total_gauss == D("11107.74")
        assert metrics.iva_reconcilia is True
        assert "bonificacion_envio" not in [code for code, _m, _c in metrics.lineas]

    def test_the_payment_alone_still_adds_up_to_what_ml_deposited(self, db) -> None:
        seed_capture(db)
        payment = db.query(MlPaymentOps).filter_by(order_id=ORDER_ID).one()

        depositado, recuperable = compute_neto_desglose_by_order_ids(db, [ORDER_ID])[ORDER_ID]

        assert D(str(payment.net_received_amount)) == D("13024.45")
        assert (depositado, recuperable) == (D("13024.45"), D("56.57"))


class TestEveryCapturedCase:
    @pytest.mark.parametrize("order_id", list(BEFORE))
    def test_total_gauss_is_identical_and_neto_grows_by_exactly_the_bonificacion(self, db, order_id) -> None:
        """THE pin. Before == after for the Total Gauss in every captured
        case, while neto / neto_sin_iva grow by the bonificación (0 where
        there is none). MUTATION: keeping the deduction in the chain AND
        adding the bonificación to the neto doubles it and fails this."""
        _seed(db, order_id)
        neto_antes, sin_iva_antes, gauss_antes = BEFORE[order_id]
        bruto, neto = BONIFICACION.get(order_id, (D("0"), D("0")))

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.total_gauss == gauss_antes
        assert metrics.neto == neto_antes + bruto
        assert metrics.neto_sin_iva == sin_iva_antes + neto
        assert metrics.iva_reconcilia is True
        assert "bonificacion_envio" not in [code for code, _m, _c in metrics.lineas]


class TestTheChainNoLongerHasIt:
    def test_it_is_not_a_deduction(self) -> None:
        assert "bonificacion_envio" not in [d.code for d in DEDUCCIONES]


class TestIvaDecomposition:
    def test_it_is_a_real_21_percent_component_not_an_informative_one(self, db) -> None:
        seed_capture(db)

        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]

        componente = next(c for c in desc.componentes if c.concepto == CONCEPTO_BONIFICACION_ENVIO)
        assert componente.informativo is False
        assert componente.alicuota == D("21")
        assert (componente.bruto, componente.base, componente.iva) == (GROSS, NET_OF_IVA, D("1560.25"))

    def test_the_components_add_up_to_the_whole_neto_exactly(self, db) -> None:
        """Payment part + bonificación == the neto the listing/panel show."""
        seed_capture(db)
        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]
        neto = compute_neto_by_order_ids(db, [ORDER_ID])[ORDER_ID]

        suma = sum((c.bruto for c in desc.componentes if not c.informativo), D("0"))

        assert suma == neto - desc.debitos_creditos_retiro
        assert desc.reconcilia is True
        assert desc.diferencia == D("0")

    def test_the_payment_part_is_reconciled_against_the_payment_alone(self, db) -> None:
        """The bonificación must not loosen the reconciliation: a payment that
        does not add up stays unreconciled even though a bonificación exists
        (it cannot absorb the gap), and `neto_sin_iva` goes unknown exactly as
        it did before. MUTATION: reconciling the whole sum against the whole
        neto lets an offsetting error through; reconciling with a tolerance
        fails the 0.01 case."""
        seed_capture(db)
        payment = db.query(MlPaymentOps).filter_by(order_id=ORDER_ID).one()
        payment.net_received_amount = payment.net_received_amount + D("0.01")
        db.commit()

        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]

        assert desc.reconcilia is False
        assert desc.diferencia == D("0.01")
        assert desc.neto_sin_iva is None

    def test_no_payment_means_nothing_to_add_the_bonificacion_to(self, db) -> None:
        seed_capture(db)
        db.query(MlPaymentOps).filter_by(order_id=ORDER_ID).one().status = "rejected"
        db.commit()

        assert compute_neto_by_order_ids(db, [ORDER_ID])[ORDER_ID] is None
        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]
        assert desc.neto_sin_iva is None
        assert [c.concepto for c in desc.componentes] == []


class TestTheTwoPathsAndThePackAgree:
    @pytest.mark.parametrize("order_id", list(BEFORE))
    def test_breakdown_and_bulk_neto_are_the_same_number(self, db, order_id) -> None:
        _seed(db, order_id)

        bulk = compute_neto_by_order_ids(db, [order_id])[order_id]
        breakdown = compute_breakdown(db, [order_id])

        assert breakdown.neto == bulk == BEFORE[order_id][0] + BONIFICACION.get(order_id, (D("0"), D("0")))[0]

    def test_the_breakdown_carries_the_line_and_the_deposit_excludes_it(self, db) -> None:
        seed_capture(db)

        breakdown = compute_breakdown(db, [ORDER_ID])

        assert breakdown.bonificacion_envio == GROSS
        line = next(l for l in breakdown.lines if l.concepto == CONCEPTO_BONIFICACION_ENVIO)
        # A negative charge adds: the panel already draws it as `(+)`.
        assert (line.monto, line.origen) == (-GROSS, "bonificacion")
        assert breakdown.retenciones_recuperables == D("56.57")
        assert breakdown.neto_depositado == D("13024.45")
        assert breakdown.neto_depositado + breakdown.retenciones_recuperables + breakdown.bonificacion_envio == (
            breakdown.neto
        )

    def test_a_sale_without_bonificacion_has_no_line(self, db) -> None:
        seed_case(db, FULFILLMENT_990)

        breakdown = compute_breakdown(db, [FULFILLMENT_990])

        assert breakdown.bonificacion_envio == D("0")
        assert all(l.concepto != CONCEPTO_BONIFICACION_ENVIO for l in breakdown.lines)

    def test_a_pack_counts_the_shipment_once_in_every_view(self, db) -> None:
        """Three orders, one shipment, one bonificación: Σ per-order neto grows
        by the shipment's amount ONCE, and the pack breakdown agrees."""
        sibling_a, sibling_b = ORDER_ID + 1, ORDER_ID + 2
        seed_capture(db)
        seed_capture(db, order_id=sibling_a, seed_shared_rows=False)
        seed_capture(db, order_id=sibling_b, seed_shared_rows=False)
        ids = [ORDER_ID, sibling_a, sibling_b]

        netos = compute_neto_by_order_ids(db, ids)
        shares = resolve_bonificacion_flex_by_order_ids(db, ids, IVA_ML_DIVISOR)
        breakdown = compute_breakdown(db, ids)

        assert sum(s.bruto for s in shares.values()) == GROSS
        assert breakdown.neto == sum(netos.values())
        assert breakdown.bonificacion_envio == GROSS
        metrics = compute_order_metrics(db, ids)
        assert sum(m.neto for m in metrics.values()) - 3 * D("13081.02") == GROSS
        assert sum(m.neto_sin_iva for m in metrics.values()) - 3 * D("10677.99") == NET_OF_IVA


class TestTheVariosBaseCountsItOnce:
    """`base_varios` = goods + the buyer's shipping + the bonificación, all
    without IVA (#1417). It is built from the SAME resolvers as before and is
    NOT derived from `neto_sin_iva`, which now also carries the bonificación:
    deriving it would count the bonificación twice."""

    def _with_varios(self, db, pct: str) -> None:
        db.add(VariosVentaPct(porcentaje=D(pct), fecha_desde=date(2020, 1, 1)))
        db.commit()

    def test_the_base_is_unchanged_and_the_percentage_applies_to_it_once(self, db) -> None:
        seed_capture(db)
        self._with_varios(db, "3.00")

        desc = descomponer_neto(db, [ORDER_ID])[ORDER_ID]
        metrics = compute_order_metrics(db, [ORDER_ID])[ORDER_ID]

        assert desc.base_varios == D("23014.05")  # the value #1417 produced
        envio = desc.envio_comprador.neto if desc.envio_comprador is not None else D("0")
        assert desc.base_varios == desc.base_venta_sin_iva + envio + NET_OF_IVA
        varios = next(m for code, m, _c in metrics.lineas if code == "varios")
        assert varios == (D("23014.05") * D("3") / D("100")).quantize(D("0.01"))  # 690.42
        # neto_sin_iva 18107.74 - costo 6000 - flex 1000 - varios 690.42
        assert metrics.total_gauss == D("10417.32")

    def test_the_total_gauss_with_varios_is_what_main_produced(self, db) -> None:
        """Same sale, same 3 %: on `origin/main` the chain gave
        10677.99 - 6000 - 1000 - 690.42 + 7429.75 = 10417.32."""
        seed_capture(db)
        self._with_varios(db, "3.00")

        assert (
            compute_order_metrics(db, [ORDER_ID])[ORDER_ID].total_gauss
            == D("10677.99") - D("6000") - D("1000") - D("690.42") + NET_OF_IVA
        )
