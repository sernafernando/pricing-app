"""Which ML tax charges are deducted, by period (ventas-ml-impuestos-informativos S1, S2).

A version in `ml_venta_impuesto_tratamiento` overrides the built-in rule (SIRTAC informational, everything else
deducted) for one exact charge name, for the sales whose `date_created` falls in its period. Every neto path must
read it: the listing, the listing's tooltip split, the panel and the IVA breakdown.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.models.ml_venta_impuesto_tratamiento import ImpuestoTratamientoVenta
from app.services.ml_ventas_desglose.breakdown_service import (
    compute_breakdown,
    compute_neto_by_order_ids,
    compute_neto_desglose_by_order_ids,
    tax_label,
)
from app.services.ml_ventas_desglose.iva import descomponer_neto
from tests.services.ml_ventas_desglose.test_iva import _item_with_frozen_cost

SOBRETASA_JUJUY = "tax_withholding_sirtac_sobretasa-jujuy"
SOBRETASA_TDF = "tax_withholding_sirtac_sobretasa-tierra_del_fuego"
SIRTAC_CABA = "tax_withholding_sirtac-caba"
DEBITOS = "tax_withholding_collector-debitos_creditos"


def _sale(db, order_id: int, sold_on: date, charges: dict, net: str = "700.00") -> None:
    """One approved sale of 1000 sold on `sold_on`, with its frozen cost and the given tax charges."""
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            date_created=datetime(sold_on.year, sold_on.month, sold_on.day, 15, tzinfo=timezone.utc),
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            seller_id=999,
        )
    )
    _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
    db.add(
        MlPaymentOps(payment_id=order_id * 10, order_id=order_id, status="approved", net_received_amount=Decimal(net))
    )
    for name, amount in charges.items():
        db.add(MlPaymentCharge(payment_id=order_id * 10, name=name, type="tax", amount=Decimal(amount)))


def _version(db, name: str, informativo: bool, desde: date, hasta: Optional[date] = None) -> None:
    db.add(ImpuestoTratamientoVenta(charge_name=name, informativo=informativo, fecha_desde=desde, fecha_hasta=hasta))


def _neto_everywhere(db, order_id: int) -> Decimal:
    """The neto of one sale, asserting the listing and the panel agree."""
    listado = compute_neto_by_order_ids(db, [order_id])[order_id]
    panel = compute_breakdown(db, [order_id])
    assert panel.neto == listado, f"listing says {listado}, panel says {panel.neto}"
    return panel.neto


class TestAnInformationalPeriod:
    def test_a_surcharge_marked_informational_is_added_back_on_every_path(self, db) -> None:
        _sale(db, 1, date(2026, 9, 10), {SOBRETASA_JUJUY: "300.00"})
        _version(db, SOBRETASA_JUJUY, True, date(2026, 9, 1))
        db.commit()

        assert _neto_everywhere(db, 1) == Decimal("1000.00")
        assert compute_neto_desglose_by_order_ids(db, [1])[1] == (Decimal("700.00"), Decimal("300.00"))
        panel = compute_breakdown(db, [1])
        assert panel.neto_depositado == Decimal("700.00")
        assert panel.retenciones_recuperables == Decimal("300.00")
        origen = {line.concepto: line.origen for line in panel.lines}
        assert origen[tax_label(SOBRETASA_JUJUY)] == "recuperable"

        result = descomponer_neto(db, [1])[1]
        assert result.reconcilia is True
        component = next(c for c in result.componentes if c.concepto == tax_label(SOBRETASA_JUJUY))
        assert component.informativo is True

    def test_a_sale_before_the_period_keeps_deducting_it(self, db) -> None:
        _sale(db, 2, date(2026, 8, 31), {SOBRETASA_JUJUY: "300.00"})
        _version(db, SOBRETASA_JUJUY, True, date(2026, 9, 1))
        db.commit()

        assert _neto_everywhere(db, 2) == Decimal("700.00")
        component = next(
            c for c in descomponer_neto(db, [2])[2].componentes if c.concepto == tax_label(SOBRETASA_JUJUY)
        )
        assert component.informativo is False

    def test_a_sale_after_a_closed_period_keeps_deducting_it(self, db) -> None:
        _sale(db, 3, date(2026, 10, 5), {SOBRETASA_JUJUY: "300.00"})
        _version(db, SOBRETASA_JUJUY, True, date(2026, 9, 1), date(2026, 9, 30))
        db.commit()

        assert _neto_everywhere(db, 3) == Decimal("700.00")

    def test_it_applies_to_that_province_only(self, db) -> None:
        _sale(db, 4, date(2026, 9, 10), {SOBRETASA_TDF: "300.00"})
        _version(db, SOBRETASA_JUJUY, True, date(2026, 9, 1))
        db.commit()

        assert _neto_everywhere(db, 4) == Decimal("700.00")


class TestPeriodsFollowEachOther:
    def test_the_latest_start_wins_on_the_day_both_cover(self, db) -> None:
        # The endpoint closes the old version ON the new one's start day, like varios.
        _sale(db, 5, date(2026, 10, 1), {SOBRETASA_JUJUY: "300.00"})
        _sale(db, 6, date(2026, 9, 30), {SOBRETASA_JUJUY: "300.00"})
        _version(db, SOBRETASA_JUJUY, True, date(2026, 9, 1), date(2026, 10, 1))
        _version(db, SOBRETASA_JUJUY, False, date(2026, 10, 1))
        db.commit()

        assert _neto_everywhere(db, 5) == Decimal("700.00")
        assert _neto_everywhere(db, 6) == Decimal("1000.00")


class TestTheBuiltInRuleCanBeTurnedAround:
    def test_sirtac_marked_deducted_stops_being_added_back(self, db) -> None:
        _sale(db, 7, date(2026, 9, 10), {SIRTAC_CABA: "300.00"})
        _version(db, SIRTAC_CABA, False, date(2026, 9, 1))
        db.commit()

        assert _neto_everywhere(db, 7) == Decimal("700.00")
        assert compute_neto_desglose_by_order_ids(db, [7])[7] == (Decimal("700.00"), Decimal("0"))
        component = next(c for c in descomponer_neto(db, [7])[7].componentes if c.concepto == tax_label(SIRTAC_CABA))
        assert component.informativo is False

    def test_sirtac_without_a_version_stays_informational(self, db) -> None:
        _sale(db, 8, date(2026, 9, 10), {SIRTAC_CABA: "300.00"})
        db.commit()

        assert _neto_everywhere(db, 8) == Decimal("1000.00")

    def test_informational_debitos_creditos_also_drops_its_withdrawal_copy(self, db) -> None:
        _sale(db, 9, date(2026, 9, 10), {DEBITOS: "300.00"})
        _version(db, DEBITOS, True, date(2026, 9, 1))
        db.commit()

        assert _neto_everywhere(db, 9) == Decimal("1000.00")
        result = descomponer_neto(db, [9])[9]
        assert result.reconcilia is True
        assert not result.debitos_creditos_retiro
