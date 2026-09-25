"""Integration tests for the order/pack scope correction (ventas-ml-rediseno
PR18, design D13, spec `ml-order-breakdown` R35-R40, `ml-sales-kpi-aggregation`
R16/R17).

`GET /orders/{order_id}` must resolve strictly against the requested order,
never the whole pack it belongs to (R35). A new `GET /packs/{pack_id}`
carries the pack-scoped figures instead (R36-R40).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.permiso import Permiso, RolPermisoBase


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant_ml_ops_ver(db, rol_admin) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(
            codigo="ml_ops.ver", nombre="Ver operaciones ML", descripcion="", categoria="ml_ops", orden=200
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_order(
    db,
    order_id: int,
    *,
    pack_id: int | None = None,
    total_amount: float = 100,
    shipping_id: int | None = None,
    date_created: datetime | None = None,
) -> None:
    if date_created is None:
        date_created = datetime(2026, 9, 1, tzinfo=timezone.utc)
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=date_created,
            date_created=date_created,
            seller_id=999,
            total_amount=total_amount,
            paid_amount=total_amount,
            currency_id="ARS",
            shipping_id=shipping_id,
        )
    )
    db.flush()


def _item(db, order_id: int, item_id: str, *, quantity: int = 1, unit_price=Decimal("100.00")) -> None:
    db.add(
        MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=quantity, unit_price=unit_price)
    )
    db.flush()


def _stored_metrics(
    db,
    order_id: int,
    *,
    total_gauss=None,
    costo_mercaderia=None,
    markup_pct=None,
    gauss_status: str = "ok",
) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=None,
            total_gauss=total_gauss,
            gauss_status=gauss_status,
            markup_pct=markup_pct,
            costo_mercaderia=costo_mercaderia,
            formula_version=1,
            computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()


class TestOrderDetailIsOrderScopedEvenInsideAPack:
    """PR18.T1/T2 (R35, scenario 4): `monto_operacion`, `total_gauss`,
    `costo_mercaderia` and `markup` for a pack member must describe ONLY
    that order, never the whole pack."""

    def test_pack_member_detail_reports_only_its_own_figures(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 1001, pack_id=500, total_amount=100, date_created=when)
        _seed_order(db, 1002, pack_id=500, total_amount=250, date_created=when)
        _item(db, 1001, "MLA1", unit_price=Decimal("100.00"))
        _item(db, 1002, "MLA2", unit_price=Decimal("250.00"))
        _stored_metrics(db, 1001, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("10.00"))
        _stored_metrics(db, 1002, total_gauss=Decimal("60.00"), costo_mercaderia=Decimal("20.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/orders/1001", headers=admin_auth_headers).json()

        # If this were still pack-scoped, monto_operacion would be 350
        # (100 + 250) and total_gauss 90.00 (30 + 60).
        assert body["breakdown"]["monto_operacion"] == pytest.approx(100.0)
        assert body["total_gauss"] == pytest.approx(30.00)
        assert body["cadena_total_gauss"]["total_gauss"] == pytest.approx(30.00)


class TestListingPackAggregationReusesSharedAggregator:
    """PR18.T7/T8: the listing's `group_total_gauss` must equal the sum of
    member `total_gauss` values -- pinned against `aggregate_pack_metrics`
    directly, not just re-derived inline."""

    def test_group_total_gauss_equals_sum_of_members(self, db, client, admin_auth_headers, rol_admin):
        from app.services.ml_ventas_desglose.pack_aggregation import aggregate_pack_metrics

        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 2001, pack_id=600, date_created=when)
        _seed_order(db, 2002, pack_id=600, date_created=when)
        _seed_order(db, 2003, pack_id=600, date_created=when)
        _stored_metrics(db, 2001, total_gauss=Decimal("10.00"), costo_mercaderia=Decimal("1.00"))
        _stored_metrics(db, 2002, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("2.00"))
        _stored_metrics(db, 2003, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("3.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        group = next(g for g in body["sales"] if g["pack_id"] == 600)

        expected = aggregate_pack_metrics(db, [2001, 2002, 2003])
        assert group["total_gauss"] == pytest.approx(float(expected.total_gauss))
        assert group["total_gauss"] == pytest.approx(60.00)


class TestPacksEndpoint:
    """PR18.T9/T10/T13/T14 (R36, R39, scenarios 5, 9)."""

    def test_pack_detail_returns_aggregated_figures_and_member_ids(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 3001, pack_id=700, total_amount=100, date_created=when)
        _seed_order(db, 3002, pack_id=700, total_amount=200, date_created=when)
        _seed_order(db, 3003, pack_id=700, total_amount=300, date_created=when)
        _item(db, 3001, "MLA1", unit_price=Decimal("100.00"))
        _item(db, 3002, "MLA2", unit_price=Decimal("200.00"))
        _item(db, 3003, "MLA3", unit_price=Decimal("300.00"))
        _stored_metrics(db, 3001, total_gauss=Decimal("10.00"), costo_mercaderia=Decimal("1.00"))
        _stored_metrics(db, 3002, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("2.00"))
        _stored_metrics(db, 3003, total_gauss=Decimal("30.00"), costo_mercaderia=Decimal("3.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/packs/700", headers=admin_auth_headers).json()

        assert body["pack_id"] == 700
        assert body["monto_operacion"] == pytest.approx(600.0)
        assert body["total_gauss"] == pytest.approx(60.00)
        assert body["costo_mercaderia"] == pytest.approx(6.00)
        assert body["markup"] == pytest.approx(1000.00)
        assert sorted(body["member_order_ids"]) == [3001, 3002, 3003]

    def test_pack_markup_is_none_when_a_member_has_no_stored_row(self, db, client, admin_auth_headers, rol_admin):
        """R37 scenario 6."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 3101, pack_id=701, date_created=when)
        _seed_order(db, 3102, pack_id=701, date_created=when)
        _stored_metrics(db, 3101, total_gauss=Decimal("10.00"), costo_mercaderia=Decimal("1.00"))
        # 3102 has no stored row.
        db.commit()

        body = client.get("/api/ml-ventas-ops/packs/701", headers=admin_auth_headers).json()

        assert body["markup"] is None
        assert body["total_gauss"] is None
        assert body["costo_mercaderia"] is None

    def test_unknown_pack_id_is_404_not_silently_treated_as_an_order_id(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """R39 scenario 9."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 3201, date_created=when)  # a real order id, NOT a pack id.
        db.commit()

        resp = client.get("/api/ml-ventas-ops/packs/3201", headers=admin_auth_headers)

        assert resp.status_code == 404

    def test_single_order_pack_degenerates_to_that_orders_own_values(self, db, client, admin_auth_headers, rol_admin):
        """R40 scenario 10 -- exercised only if PR18.T15 finds this case
        reachable; see that task's VERIFY note. This fixture is
        defensive-only: it asserts the endpoint's OWN behavior for a
        single-member pack_id, not that ML actually assigns one in
        production data."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 3301, pack_id=702, total_amount=150, date_created=when)
        _item(db, 3301, "MLA1", unit_price=Decimal("150.00"))
        _stored_metrics(
            db, 3301, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("5.00"), markup_pct=Decimal("1000.00")
        )
        db.commit()

        pack_body = client.get("/api/ml-ventas-ops/packs/702", headers=admin_auth_headers).json()
        order_body = client.get("/api/ml-ventas-ops/orders/3301", headers=admin_auth_headers).json()

        assert pack_body["monto_operacion"] == pytest.approx(order_body["breakdown"]["monto_operacion"])
        assert pack_body["total_gauss"] == pytest.approx(order_body["total_gauss"])
        assert pack_body["markup"] == pytest.approx(order_body["cadena_total_gauss"]["markup"])
        assert pack_body["member_order_ids"] == [3301]


class TestFlexShippingProrationLabel:
    """PR18.T18/T19 (R38, scenario 8)."""

    def test_shared_shipment_line_is_labeled_prorated(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 4001, pack_id=800, shipping_id=9000, date_created=when)
        _seed_order(db, 4002, pack_id=800, shipping_id=9000, date_created=when)
        _stored_metrics(db, 4001, total_gauss=Decimal("10.00"), costo_mercaderia=Decimal("1.00"))
        db.commit()
        from app.models.ml_venta_deduccion import MlVentaDeduccion

        db.add(MlVentaDeduccion(order_id=4001, code="envio_flex", monto=Decimal("5.00"), orden=2))
        db.commit()

        body = client.get("/api/ml-ventas-ops/orders/4001", headers=admin_auth_headers).json()

        flex_line = next(l for l in body["cadena_total_gauss"]["lineas"] if l["code"] == "envio_flex")
        assert flex_line["prorateado"] is True

    def test_standalone_order_flex_line_is_not_labeled_prorated(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 4101, shipping_id=9100, date_created=when)
        _stored_metrics(db, 4101, total_gauss=Decimal("10.00"), costo_mercaderia=Decimal("1.00"))
        db.commit()
        from app.models.ml_venta_deduccion import MlVentaDeduccion

        db.add(MlVentaDeduccion(order_id=4101, code="envio_flex", monto=Decimal("5.00"), orden=2))
        db.commit()

        body = client.get("/api/ml-ventas-ops/orders/4101", headers=admin_auth_headers).json()

        flex_line = next(l for l in body["cadena_total_gauss"]["lineas"] if l["code"] == "envio_flex")
        assert flex_line["prorateado"] is False
