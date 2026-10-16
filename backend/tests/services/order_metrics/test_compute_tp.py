"""TP-Link figures of one order (metricas-ml-tplink-mode P3): `costo_tp`,
`total_tp`, `markup_tp` and the `tp_incompleto` flag, computed by
`compute_order_metrics` next to the Gauss ones.

Total TP = total_gauss + costo_mercaderia - costo_tp; Markup TP = Total TP /
costo_tp. A missing TP cost on ANY item leaves every TP figure NULL and the
flag set: never 0, never the normal cost.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _order(db, order_id: int, *, paid: Optional[str] = None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
        )
    )
    if paid is not None:
        db.add(
            MlPaymentOps(payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal(paid))
        )


def _item(db, order_id: int, item_id: str, qty: int, costo: str, costo_tp: Optional[str], *, cost_row=True) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=qty))
    if not cost_row:
        return
    tp = {}
    if costo_tp is not None:
        tp = dict(
            costo_tp_origen=Decimal(costo_tp),
            costo_tp_moneda="ARS",
            costo_tp_unitario_ars=Decimal(costo_tp),
            costo_tp_fuente="lista8_ingesta",
            costo_tp_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            costo_origen=Decimal(costo),
            moneda="ARS",
            costo_unitario_ars=Decimal(costo),
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("100.00"),
            fuente="sku",
            producto_item_id=1,
            **tp,
        )
    )


def _varios(db) -> None:
    db.add(VariosVentaPct(porcentaje=Decimal("0.00"), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


class TestTpFigures:
    def test_complete_order_carries_cost_total_and_markup_tp(self, db) -> None:
        _order(db, 7001, paid="300.00")
        _item(db, 7001, "MLA1", 2, "10.00", "8.00")
        _item(db, 7001, "MLA2", 1, "100.00", "70.335")
        _varios(db)
        db.commit()

        m = compute_order_metrics(db, [7001])[7001]

        assert m.gauss_status == GaussStatus.OK
        assert m.costo_mercaderia == Decimal("120.00")
        # Per item, rounded to the cent like the normal cost: 16.00 + 70.34.
        assert m.costo_tp == Decimal("86.34")
        assert m.total_tp == m.total_gauss + m.costo_mercaderia - Decimal("86.34")
        assert m.markup_tp == (m.total_tp / Decimal("86.34") * 100).quantize(Decimal("0.01"))
        assert m.tp_incompleto is False

    def test_one_item_without_tp_cost_leaves_every_tp_figure_null(self, db) -> None:
        _order(db, 7002, paid="300.00")
        _item(db, 7002, "MLA1", 2, "10.00", "8.00")
        _item(db, 7002, "MLA2", 1, "100.00", None)
        _varios(db)
        db.commit()

        m = compute_order_metrics(db, [7002])[7002]

        assert m.total_gauss is not None and m.costo_mercaderia == Decimal("120.00")
        assert (m.costo_tp, m.total_tp, m.markup_tp) == (None, None, None)
        assert m.tp_incompleto is True

    def test_an_item_with_no_frozen_cost_row_is_incomplete_too(self, db) -> None:
        _order(db, 7003, paid="300.00")
        _item(db, 7003, "MLA1", 2, "10.00", "8.00")
        _item(db, 7003, "MLA2", 1, "100.00", None, cost_row=False)
        _varios(db)
        db.commit()

        m = compute_order_metrics(db, [7003])[7003]

        assert (m.costo_tp, m.total_tp, m.markup_tp, m.tp_incompleto) == (None, None, None, True)

    def test_unresolved_gauss_keeps_the_tp_cost_but_no_total_tp(self, db) -> None:
        _order(db, 7004)  # no payment: Total Gauss is unresolved
        _item(db, 7004, "MLA1", 2, "10.00", "8.00")
        _varios(db)
        db.commit()

        m = compute_order_metrics(db, [7004])[7004]

        assert m.gauss_status == GaussStatus.UNRESOLVED
        assert m.costo_tp == Decimal("16.00")
        assert (m.total_tp, m.markup_tp) == (None, None)
        assert m.tp_incompleto is False

    def test_zero_tp_cost_has_a_total_but_no_markup(self, db) -> None:
        _order(db, 7005, paid="100.00")
        _item(db, 7005, "MLA1", 1, "10.00", "0")
        _varios(db)
        db.commit()

        m = compute_order_metrics(db, [7005])[7005]

        assert m.costo_tp == Decimal("0.00")
        assert m.total_tp == m.total_gauss + m.costo_mercaderia
        assert m.markup_tp is None
        assert m.tp_incompleto is False


def _metrics(**overrides) -> OrderMetrics:
    values = dict(
        order_id=1,
        neto=Decimal("100"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal("30"),
        total_gauss=Decimal("50"),
        markup_pct=Decimal("166.67"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=7,
        computed_at=datetime.now(timezone.utc),
    )
    values.update(overrides)
    return OrderMetrics(**values)


class TestTpInvariants:
    def test_incomplete_order_cannot_carry_a_tp_figure(self) -> None:
        with pytest.raises(ValueError):
            _metrics(costo_tp=Decimal("20"), tp_incompleto=True)
        with pytest.raises(ValueError):
            _metrics(total_tp=Decimal("60"), tp_incompleto=True)

    def test_total_tp_needs_a_total_gauss_and_a_tp_cost(self) -> None:
        with pytest.raises(ValueError):
            _metrics(
                total_gauss=None,
                markup_pct=None,
                gauss_status=GaussStatus.UNRESOLVED,
                costo_tp=Decimal("20"),
                total_tp=Decimal("60"),
                tp_incompleto=False,
            )
        with pytest.raises(ValueError):
            _metrics(total_tp=Decimal("60"), tp_incompleto=False)

    def test_markup_tp_needs_a_nonzero_tp_cost(self) -> None:
        with pytest.raises(ValueError):
            _metrics(costo_tp=Decimal("0"), total_tp=Decimal("80"), markup_tp=Decimal("1"), tp_incompleto=False)

    def test_legacy_construction_without_tp_fields_still_works(self) -> None:
        m = _metrics()
        assert (m.costo_tp, m.total_tp, m.markup_tp, m.tp_incompleto) == (None, None, None, None)


class TestTpFiguresAreStored:
    def test_a_recompute_stores_the_tp_cost_a_backfill_filled_in_later(self, db) -> None:
        from app.models.ml_order_metrics import MlOrderMetrics
        from app.services.order_metrics.store import recompute_order_metrics

        _order(db, 7101, paid="200.00")
        _item(db, 7101, "MLA1", 2, "10.00", None)
        _varios(db)
        db.commit()

        recompute_order_metrics(db, [7101])
        db.commit()
        row = db.get(MlOrderMetrics, 7101)
        assert (row.costo_tp, row.total_tp, row.markup_tp, row.tp_incompleto) == (None, None, None, True)

        # What P2's backfill does: fill the NULL TP cost of the frozen row once.
        costo = db.query(MlOrderItemCosto).filter_by(order_id=7101).one()
        costo.costo_tp_origen = Decimal("8.00")
        costo.costo_tp_moneda = "ARS"
        costo.costo_tp_unitario_ars = Decimal("8.00")
        costo.costo_tp_fuente = "lista8_historia"
        costo.costo_tp_at = datetime(2026, 10, 16, tzinfo=timezone.utc)
        db.commit()

        stored = recompute_order_metrics(db, [7101])[7101]
        db.commit()
        db.expire_all()
        row = db.get(MlOrderMetrics, 7101)
        assert row.costo_tp == Decimal("16.00")
        assert row.total_tp == stored.total_tp == row.total_gauss + row.costo_mercaderia - Decimal("16.00")
        assert row.markup_tp == stored.markup_tp
        assert row.tp_incompleto is False
