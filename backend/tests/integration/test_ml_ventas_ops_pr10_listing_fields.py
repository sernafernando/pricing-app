"""Integration tests for PR10 (ventas-ml-rediseno) -- additive listing
fields on `GET /api/ml-ventas-ops/sales` (design D13, spec ml-sales-listing
R28-R31).

Reuses the shared fixtures/helpers from `test_ml_ventas_ops_sales_router.py`
(`_seed_order`, `_grant_ml_ops_ver`, `_group_holding`, `_payment`,
`_stored_metrics`) rather than duplicating them -- this file only adds the
scenarios specific to the new fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.models.producto import ProductoERP
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION

from .test_ml_ventas_ops_sales_router import (
    _charge,
    _grant_ml_ops_ver,
    _group_holding,
    _payment,
    _seed_order,
    _stored_metrics,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _frozen_cost(db, order_id: int, producto_item_id: int, item_id: str = "MLA1") -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=1))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            costo_origen=Decimal("10.00"),
            moneda="ARS",
            costo_unitario_ars=Decimal("10.00"),
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("121.00"),
            fuente="sku",
            producto_item_id=producto_item_id,
        )
    )


def _producto(db, item_id: int, categoria: str) -> None:
    db.add(ProductoERP(item_id=item_id, codigo=f"COD-{item_id}", descripcion="d", categoria=categoria))


class TestItemCategoryAdditiveField:
    """PR10.T1/T2 (spec LISTING R28): `item_category`, resolved through the
    frozen-cost linkage, additive -- never changes any existing field."""

    def test_order_with_frozen_cost_exposes_its_erp_category(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95001
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _producto(db, 501, "Impresoras")
        _frozen_cost(db, order_id, producto_item_id=501)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["orders"][0]["item_category"] == "Impresoras"

    def test_order_with_no_frozen_cost_row_has_null_category_not_ml_category_id(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """No `ml_order_item_costos` row at all -- must be `None`, never a
        fabricated category and never ML's own opaque `category_id`."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95002
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["orders"][0]["item_category"] is None

    def test_order_with_several_items_keeps_the_first_items_category(self, db, client, admin_auth_headers, rol_admin):
        """An order with TWO frozen-cost items must show only ONE category
        -- the FIRST item's (ordered by `MlOrderItemCosto.id`), never the
        last one silently overwriting it."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95004
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _producto(db, 503, "Impresoras")
        _producto(db, 504, "Cables")
        _frozen_cost(db, order_id, producto_item_id=503, item_id="MLA-FIRST")
        db.flush()
        _frozen_cost(db, order_id, producto_item_id=504, item_id="MLA-SECOND")
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["orders"][0]["item_category"] == "Impresoras"

    def test_existing_fields_are_unchanged_by_the_new_join(self, db, client, admin_auth_headers, rol_admin):
        """Additive-only regression guard (LISTING R28): adding the category
        join must not perturb an already-shipped field's value."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95003
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _producto(db, 502, "Cables")
        _frozen_cost(db, order_id, producto_item_id=502)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["orders"][0]["status"] == "paid"
        assert sale["orders"][0]["order_id"] == order_id


class TestReceiverAddressAndShipmentAdditiveFields:
    """PR10.T3/T4 (spec LISTING R28): `city`, `province`,
    `shipping_substatus`, captured-fixture based, null-safe on a missing
    key, a null value or an unexpected type."""

    def test_real_captured_shape_resolves_city_and_province(self, db, client, admin_auth_headers, rol_admin):
        """Real shape verified against `ml_webhook_service.py`'s own
        parsing: `{"city": {"name": ...}, "state": {"name": ...}}`."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95010
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc), shipping_status="shipped")
        db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order_id * 10).update(
            {
                "receiver_address": {"city": {"name": "Carbometal"}, "state": {"name": "Mendoza"}},
                "substatus": "out_for_delivery",
            }
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["city"] == "Carbometal"
        assert order["province"] == "Mendoza"
        assert order["shipping_substatus"] == "out_for_delivery"

    def test_missing_city_key_is_null_not_an_error(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95011
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc), shipping_status="shipped")
        db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order_id * 10).update(
            {"receiver_address": {"state": {"name": "Mendoza"}}}
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["city"] is None
        assert order["province"] == "Mendoza"

    def test_null_city_value_is_null_not_an_error(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95012
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc), shipping_status="shipped")
        db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order_id * 10).update(
            {"receiver_address": {"city": None, "state": {"name": "Mendoza"}}}
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["city"] is None

    def test_unexpected_type_shape_is_null_not_a_500(self, db, client, admin_auth_headers, rol_admin):
        """`city` as a bare string (not the expected `{"name": ...}` dict)
        -- an unexpected but real-world-possible ML payload shape."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95013
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc), shipping_status="shipped")
        db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order_id * 10).update(
            {"receiver_address": {"city": "Carbometal", "state": {"name": "Mendoza"}}}
        )
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        order = _group_holding(resp.json(), order_id)["orders"][0]
        assert order["city"] is None

    def test_no_shipment_at_all_leaves_every_shipment_field_null(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95014
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["city"] is None
        assert order["province"] is None
        assert order["shipping_substatus"] is None


class TestCouponAmountAdditiveField:
    """PR10.T3/T4 (spec LISTING R28): `coupon_amount`, summed across every
    RELEVANT payment of the order -- one bulk query for the whole page."""

    def test_coupon_amount_sums_relevant_payments(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95020
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(
            MlPaymentOps(
                payment_id=95020,
                order_id=order_id,
                status="approved",
                net_received_amount=Decimal("100.00"),
                coupon_amount=Decimal("15.50"),
            )
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["coupon_amount"] == pytest.approx(15.50)

    def test_no_relevant_payment_is_null_not_zero(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95021
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["coupon_amount"] is None


class TestAlertLevel:
    """PR10.T5/T6 (design D13, spec LISTING R29): unified server-derived
    alert level, replacing ad-hoc per-field FE flags."""

    def test_unresolved_stored_metrics_is_error(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95030
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="unresolved", total_gauss=None)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["alert_level"] == "error"

    def test_no_stored_metrics_at_all_is_error(self, db, client, admin_auth_headers, rol_admin):
        """`pending` (never computed) -- `neto` is null, so it must read as
        an error, same as an explicitly `unresolved` row."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95031
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["alert_level"] == "error"
        assert order["metrics_state"] == "pending"

    def test_provisional_stored_metrics_is_warning(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95032
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="provisional", total_gauss=Decimal("10.00"), neto=Decimal("10.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["alert_level"] == "warning"

    def test_recalculating_dirty_row_is_warning(self, db, client, admin_auth_headers, rol_admin):
        """A dirty (mid-recompute) row wins over an already-`ok` stored one
        -- `metrics_state_for_orders`'s own precedence, reused here."""
        from app.models.ml_order_metrics import MlOrderMetricsDirty

        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95033
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"), neto=Decimal("10.00"))
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=0))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["metrics_state"] == "recalculating"
        assert order["alert_level"] == "warning"

    def test_iva_not_reconciling_is_warning_even_when_gauss_status_ok(self, db, client, admin_auth_headers, rol_admin):
        """Both status axes are fully resolved (`delivered`) here on
        purpose: only `iva_reconcilia=False` may explain the `warning`, or
        this test would pass for the wrong reason (an `unknown` axis would
        also warn, hiding a broken `iva_reconcilia` check)."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95034
        _seed_order(
            db,
            order_id,
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
            status="delivered",
            shipping_status="delivered",
        )
        db.add(
            MlOrderMetrics(
                order_id=order_id,
                neto=Decimal("10.00"),
                total_gauss=Decimal("10.00"),
                gauss_status="ok",
                iva_reconcilia=False,
                formula_version=CURRENT_FORMULA_VERSION,
                computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["alert_level"] == "warning"

    def test_unknown_operation_status_is_warning_even_when_metrics_ok(self, db, client, admin_auth_headers, rol_admin):
        """An `unknown` operation/goods status (no shipment, unresolved
        claim signal) is a warning on its own, independent of the metrics
        state -- design D13's 'op or goods unknown' branch."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95035
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc), status="paid")
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"), neto=Decimal("10.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        # A `paid` order with no shipment and no claim resolves goods_status
        # to `unknown` (existing derivation, ml-orders-ingestion), so this
        # order's alert must warn even though its own metrics are `ok`.
        assert order["goods_status"] == "unknown"
        assert order["alert_level"] == "warning"

    def test_fully_ok_order_is_ok(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95036
        _seed_order(
            db,
            order_id,
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
            status="delivered",
            shipping_status="delivered",
        )
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"), neto=Decimal("10.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["alert_level"] == "ok"


class TestListingReadsStoredMetricsNeverLiveRecompute:
    """PR10.T7 -- explicit regression guard (design D2/D13, spec LISTING
    R31): the listing's `neto`, `total_gauss` and `markup` must equal the
    `ml_order_metrics` stored row, not a live recompute -- pins the exact
    failure mode this task warned about (verified failing before this
    change: the listing called `compute_neto_by_order_ids`/
    `calcular_total_gauss` directly, ignoring the stored row entirely)."""

    def test_listing_shows_the_stored_value_even_when_live_inputs_would_disagree(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95040
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        # Live inputs that WOULD recompute to a real number if the listing
        # still called the live chain -- deliberately never fed into
        # `ml_order_metrics`.
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        # The STORED row instead carries a deliberately different number.
        _stored_metrics(
            db,
            order_id,
            gauss_status="ok",
            total_gauss=Decimal("42.00"),
            markup_pct=Decimal("55.00"),
            costo_mercaderia=Decimal("1.00"),
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["total_gauss"] == pytest.approx(42.00)
        assert order["markup"] == pytest.approx(55.00)
        # `neto` has no stored value on this deliberately hand-seeded row
        # (`_stored_metrics` defaults `neto=None`) -- the live payment above
        # must NOT leak through as a fallback.
        assert order["neto"] is None

    def test_markup_is_a_new_additive_field_never_populated_before(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95041
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(
            db,
            order_id,
            gauss_status="ok",
            total_gauss=Decimal("90.00"),
            markup_pct=Decimal("900.00"),
            costo_mercaderia=Decimal("10.00"),
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["markup"] == pytest.approx(900.00)


class TestMetricsStateField:
    """PR10.T8: `metrics_state` present per row, reusing
    `metrics_state_for_orders`'s exact precedence -- never re-derived."""

    def test_ok_state(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95050
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = _group_holding(body, order_id)["orders"][0]
        assert order["metrics_state"] == "ok"

    def test_failed_state_wins_over_stored_ok(self, db, client, admin_auth_headers, rol_admin):
        """A parked (poisoned) dirty row reports `failed`, even though a
        (now stale) `ok` stored row exists -- `metrics_state_for_orders`'s
        own top precedence."""
        from app.models.ml_order_metrics import MlOrderMetricsDirty
        from app.services.order_metrics.queue import POISON_THRESHOLD

        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95051
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"))
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=POISON_THRESHOLD))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = _group_holding(body, order_id)["orders"][0]
        assert order["metrics_state"] == "failed"

    def test_pending_state_when_no_row_at_all(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95052
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = _group_holding(body, order_id)["orders"][0]
        assert order["metrics_state"] == "pending"


class TestNetoDepositadoIsPaymentsOnlyRegardlessOfMetricsState:
    """PR10 review finding N1 (corrected): `neto_depositado`/
    `retenciones_recuperables` are a LIVE computation over payments/charges
    only (`compute_neto_desglose_by_order_ids`), deliberately never gated
    by `order_metrics_state`. The property that actually holds and is worth
    pinning: a recompute triggered by a NON-payment input (a cost change,
    for instance) leaves this live figure unchanged, because it never read
    that input to begin with -- there is no second clock to reconcile
    there. Divergence is only possible when the payments themselves
    changed, and that is exactly what marks the row dirty."""

    def test_recalculating_from_a_non_payment_change_leaves_neto_depositado_unchanged(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """The order is dirty (mid-flight) from a COST change, not a
        payment change -- its stored `neto` is stale (SM R6), but its
        payments/charges never moved, so `neto_depositado`/
        `retenciones_recuperables` must read the SAME value they would for
        a settled row with identical payments."""
        from app.models.ml_order_metrics import MlOrderMetricsDirty

        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95070
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("999.00"), neto=Decimal("999.00"))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("800.00"))
        _charge(db, order_id, "tax_withholding_sirtac-caba", "tax", Decimal("300.00"))
        # Dirty for a reason unrelated to payments (e.g. a cost update) --
        # `reason` is free text, what matters is payments are untouched.
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="costo_mercaderia changed", attempts=0))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["orders"][0]["metrics_state"] == "recalculating"
        # The stored `neto` is still the stale one (SM R6) ...
        assert sale["neto"] == pytest.approx(999.00)
        # ... but `neto_depositado`/`retenciones_recuperables` read the
        # CURRENT payments/charges regardless -- unaffected by the stale
        # stored `neto`/`total_gauss` above them.
        assert sale["neto_depositado"] == pytest.approx(800.00)
        assert sale["retenciones_recuperables"] == pytest.approx(300.00)
        assert sale["orders"][0]["neto_depositado"] == pytest.approx(800.00)
        assert sale["orders"][0]["retenciones_recuperables"] == pytest.approx(300.00)

    def test_pending_row_still_carries_live_neto_depositado(self, db, client, admin_auth_headers, rol_admin):
        """No stored row at all (`neto` is `None`, PR10.T7): the live
        `neto_depositado`/`retenciones_recuperables` are still shown --
        they carry real, correct payment information the user should not
        lose just because the Gauss chain has not computed yet."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95071
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("500.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert order["metrics_state"] == "pending"
        assert order["neto"] is None
        assert order["neto_depositado"] == pytest.approx(500.00)


class TestPR10DoesNotIntroduceNPlusOne:
    """Every new bulk lookup (`item_category`, `coupon_amount`, stored
    metrics, `metrics_state`) must stay at ONE query each for the whole
    page -- never one per row."""

    def test_five_rows_stay_within_a_fixed_query_budget(self, db, client, admin_auth_headers, rol_admin, query_counter):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        for i in range(5):
            order_id = 95060 + i
            _seed_order(db, order_id, date_created=when)
            _producto(db, 600 + i, "Cables")
            _frozen_cost(db, order_id, producto_item_id=600 + i, item_id=f"MLA{i}")
            _stored_metrics(db, order_id, gauss_status="ok", total_gauss=Decimal("10.00"))
        db.commit()

        with query_counter() as counter:
            resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)
        assert resp.status_code == 200

        assert counter.matching("ml_order_item_costos") <= 1
        assert counter.matching("ml_order_metrics") <= 2  # read_stored_metrics + metrics_state_for_orders
        assert counter.matching("ml_payments_ops") <= 2  # coupon_amount_by_order + neto_desglose
        assert counter.matching("ml_order_items_ops") <= 1  # items_by_order


class TestItemsAdditiveField:
    """ventas-ml-producto-listado-pr10b: `items` on `SaleListItem`, reusing
    the SAME `OrderItemOpsSummary` shape `GET /orders/{id}` already exposes
    (title/seller_sku/item_id/variation_id/quantity/unit_price) -- an order
    can carry several items, so a flat `title`/`seller_sku` pair on the row
    would silently pick one and lie about the rest."""

    def test_single_item_order_exposes_its_item(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95080
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id="MLA1000",
                seller_sku="SKU-A",
                title="Producto A",
                quantity=2,
                unit_price=Decimal("50.00"),
            )
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert len(order["items"]) == 1
        item = order["items"][0]
        assert item["item_id"] == "MLA1000"
        assert item["seller_sku"] == "SKU-A"
        assert item["title"] == "Producto A"
        assert item["quantity"] == 2
        assert item["unit_price"] == pytest.approx(50.00)

    def test_multi_item_order_returns_every_item(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95081
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(MlOrderItemOps(order_id=order_id, item_id="MLA2000", seller_sku="SKU-B1", title="B1", quantity=1))
        db.add(MlOrderItemOps(order_id=order_id, item_id="MLA2001", seller_sku="SKU-B2", title="B2", quantity=3))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        order = _group_holding(body, order_id)["orders"][0]
        assert len(order["items"]) == 2
        item_ids = {item["item_id"] for item in order["items"]}
        assert item_ids == {"MLA2000", "MLA2001"}

    def test_order_with_no_items_returns_empty_list_not_500(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 95082
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        order = _group_holding(resp.json(), order_id)["orders"][0]
        assert order["items"] == []

    def test_two_orders_on_the_same_page_never_leak_items_into_each_other(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """The bulk lookup groups in Python -- a wrong grouping key (e.g.
        the first row's order_id) would silently merge every order's items
        under one bucket without any error, so an order-scoped assertion
        with TWO orders on the page is the only way to catch that."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        order_a, order_b = 95083, 95084
        _seed_order(db, order_a, date_created=when)
        _seed_order(db, order_b, date_created=when)
        db.add(MlOrderItemOps(order_id=order_a, item_id="MLA-A", seller_sku="SKU-A", quantity=1))
        db.add(MlOrderItemOps(order_id=order_b, item_id="MLA-B", seller_sku="SKU-B", quantity=1))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        items_a = _group_holding(body, order_a)["orders"][0]["items"]
        items_b = _group_holding(body, order_b)["orders"][0]["items"]
        assert [i["item_id"] for i in items_a] == ["MLA-A"]
        assert [i["item_id"] for i in items_b] == ["MLA-B"]

    def test_items_stay_within_one_bulk_query_for_the_page(
        self, db, client, admin_auth_headers, rol_admin, query_counter
    ):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        for i in range(5):
            order_id = 95090 + i
            _seed_order(db, order_id, date_created=when)
            db.add(MlOrderItemOps(order_id=order_id, item_id=f"MLA30{i}", seller_sku=f"SKU-{i}", quantity=1))
        db.commit()

        with query_counter() as counter:
            resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        assert counter.matching("ml_order_items_ops") <= 1
