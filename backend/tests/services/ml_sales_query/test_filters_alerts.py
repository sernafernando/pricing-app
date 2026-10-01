"""ODD `ventas-ml-ui-pendiente` T5: the "Solo con alertas" filter.

A group has an alert when ANY member order's `alert_level` (see
`ml_ventas_ops._alert_level`) is not `ok`. The level is derived in Python in
the router, so the filter carries a SQL equivalent that must agree with it:
`_group_alert_subquery`. These tests pin each condition of that equivalent;
the router-level parity test (`test_ml_ventas_ops_alerts_router.py`) proves it
matches the Python level row by row.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.services.ml_sales_query.filters import SalesFilter, alert_groups_count, build_scope


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _order(db, order_id, *, status="paid", shipping_status="delivered", pack_id=None):
    shipping_id = order_id * 10 if shipping_status is not None else None
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            ml_last_updated=NOW,
            date_created=NOW,
            seller_id=999,
            total_amount=100,
            paid_amount=100,
            currency_id="ARS",
            shipping_id=shipping_id,
        )
    )
    if shipping_id is not None:
        db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping_status))
    db.flush()


def _metrics(db, order_id, *, gauss_status="ok", neto=100, iva_reconcilia=True):
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=neto,
            neto_sin_iva=80 if neto is not None else None,
            iva_reconcilia=iva_reconcilia,
            costo_mercaderia=50,
            total_gauss=30 if gauss_status != "unresolved" else None,
            markup_pct=60 if gauss_status != "unresolved" else None,
            gauss_status=gauss_status,
            formula_version=1,
            computed_at=NOW,
        )
    )
    db.flush()


def _keys(db, f):
    scope = build_scope(db, f)
    return {r.group_key for r in scope.listing_query.with_entities(scope.group_key.label("group_key")).all()}


def _clean_order(db, order_id, **kw):
    _order(db, order_id, **kw)
    _metrics(db, order_id)


class TestOnlyAlerts:
    def test_default_does_not_filter(self, db):
        _clean_order(db, 1)
        assert _keys(db, SalesFilter()) == {"o:1"}

    def test_clean_order_has_no_alert(self, db):
        _clean_order(db, 1)
        assert _keys(db, SalesFilter(only_alerts=True)) == set()

    @pytest.mark.parametrize(
        "metrics_kwargs",
        [
            {"gauss_status": "provisional"},
            {"gauss_status": "unresolved"},
            {"neto": None},
            {"iva_reconcilia": False},
        ],
    )
    def test_stored_metric_problems_raise_an_alert(self, db, metrics_kwargs):
        _order(db, 2)
        _metrics(db, 2, **metrics_kwargs)
        assert _keys(db, SalesFilter(only_alerts=True)) == {"o:2"}

    def test_iva_reconcilia_unknown_is_not_an_alert(self, db):
        _order(db, 3)
        _metrics(db, 3, iva_reconcilia=None)
        assert _keys(db, SalesFilter(only_alerts=True)) == set()

    def test_order_without_metrics_row_is_pending_hence_an_alert(self, db):
        _order(db, 4)
        assert _keys(db, SalesFilter(only_alerts=True)) == {"o:4"}

    def test_dirty_row_means_recalculating_or_failed_hence_an_alert(self, db):
        _clean_order(db, 5)
        db.add(MlOrderMetricsDirty(order_id=5, reason="test", attempts=0))
        db.flush()
        assert _keys(db, SalesFilter(only_alerts=True)) == {"o:5"}

    def test_unknown_goods_status_is_an_alert(self, db):
        _order(db, 6, shipping_status=None)
        _metrics(db, 6)
        assert _keys(db, SalesFilter(only_alerts=True, include_unknown=True)) == {"o:6"}

    def test_unknown_operation_status_is_an_alert(self, db):
        _order(db, 7, status="pending_payment", shipping_status="ready_to_ship")
        _metrics(db, 7)
        assert _keys(db, SalesFilter(only_alerts=True, include_unknown=True)) == {"o:7"}

    def test_a_pack_has_an_alert_when_any_member_does(self, db):
        _order(db, 10, pack_id=500)
        _metrics(db, 10)
        _order(db, 11, pack_id=500)
        _metrics(db, 11, gauss_status="provisional")
        assert _keys(db, SalesFilter(only_alerts=True)) == {"p:500"}

    def test_it_composes_with_the_other_scope_filters(self, db):
        _order(db, 20)
        _metrics(db, 20, gauss_status="provisional")
        _order(db, 21, status="cancelled")
        _metrics(db, 21, gauss_status="provisional")
        f = SalesFilter(only_alerts=True, include_provisional=True, include_cancelled=False)
        assert _keys(db, f) == {"o:20"}


class TestAlertCount:
    def test_counts_groups_with_an_alert_in_the_scope_ignoring_the_toggle_itself(self, db):
        _clean_order(db, 30)
        _order(db, 31)
        _metrics(db, 31, gauss_status="provisional")
        _order(db, 32)  # pending: no metrics
        for only_alerts in (False, True):
            scope = build_scope(db, SalesFilter(only_alerts=only_alerts))
            assert alert_groups_count(scope) == 2

    def test_respects_the_other_filters(self, db):
        _order(db, 40)
        _metrics(db, 40, gauss_status="provisional")
        _order(db, 41, status="cancelled")
        _metrics(db, 41, gauss_status="provisional")
        scope = build_scope(db, SalesFilter(include_cancelled=False))
        assert alert_groups_count(scope) == 1
