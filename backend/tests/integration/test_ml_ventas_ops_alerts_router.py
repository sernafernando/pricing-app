"""ODD `ventas-ml-ui-pendiente` T5: `only_alerts` on `GET /sales` and
`GET /sales/kpis`, plus the `facets.alerts_total` counter.

The load-bearing test is the parity one: the filter is a SQL equivalent of the
Python `_alert_level`, so for a mixed bag of sales it must keep EXACTLY the
groups whose rows show an alert (`alert_level != ok` on any member).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.models.permiso import Permiso, RolPermisoBase

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
ALL_ON = {
    "include_unknown": "true",
    "include_in_dispute": "true",
    "include_mixed": "true",
    "include_provisional": "true",
    "include_cancelled": "true",
}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant(db, rol_admin):
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(codigo="ml_ops.ver", nombre="Ver", descripcion="", categoria="ml_ops", orden=200)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _sale(
    db, order_id, *, pack_id=None, status="paid", shipping="delivered", metrics="ok", neto=80, iva=True, dirty=False
):
    shipping_id = order_id * 10 if shipping else None
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
            payment_status="approved",
        )
    )
    if shipping_id:
        db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping))
    db.flush()
    db.add(MlPaymentOps(payment_id=order_id * 10 + 1, order_id=order_id, status="approved", date_approved=NOW))
    if metrics:
        db.add(
            MlOrderMetrics(
                order_id=order_id,
                neto=neto,
                neto_sin_iva=70 if neto is not None else None,
                iva_reconcilia=iva,
                costo_mercaderia=50,
                total_gauss=30 if metrics != "unresolved" else None,
                markup_pct=60 if metrics != "unresolved" else None,
                gauss_status=metrics,
                formula_version=1,
                computed_at=NOW,
            )
        )
    if dirty:
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=0))
    db.flush()


def _seed_mixed_bag(db):
    _sale(db, 1)  # clean
    _sale(db, 2, metrics="provisional")
    _sale(db, 3, metrics="unresolved")
    _sale(db, 4, neto=None)
    _sale(db, 5, iva=False)
    _sale(db, 6, metrics=None)  # pending
    _sale(db, 7, dirty=True)  # recalculating
    _sale(db, 8, shipping=None)  # goods unknown
    _sale(db, 9, status="cancelled")  # clean cancelled
    _sale(db, 10, pack_id=900)  # pack: clean member
    _sale(db, 11, pack_id=900, metrics="provisional")  # pack: alerting member
    _sale(db, 12, pack_id=901)  # clean pack
    _sale(db, 13, pack_id=901)
    db.commit()


def _groups_with_alert(listing):
    return {g["group_key"] for g in listing["sales"] if any(o["alert_level"] != "ok" for o in g["orders"])}


def test_filter_keeps_exactly_the_groups_that_show_an_alert(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _seed_mixed_bag(db)

    everything = client.get(
        "/api/ml-ventas-ops/sales", params={**ALL_ON, "limit": 200}, headers=admin_auth_headers
    ).json()
    expected = _groups_with_alert(everything)
    assert expected  # the bag really has alerts, and clean groups too
    assert len(expected) < everything["total"]

    filtered = client.get(
        "/api/ml-ventas-ops/sales",
        params={**ALL_ON, "only_alerts": "true", "limit": 200},
        headers=admin_auth_headers,
    ).json()

    assert {g["group_key"] for g in filtered["sales"]} == expected
    assert filtered["total"] == len(expected)


def test_counter_counts_alert_groups_with_and_without_the_filter(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _seed_mixed_bag(db)
    everything = client.get(
        "/api/ml-ventas-ops/sales", params={**ALL_ON, "limit": 200}, headers=admin_auth_headers
    ).json()
    expected = len(_groups_with_alert(everything))

    off = client.get("/api/ml-ventas-ops/sales", params=ALL_ON, headers=admin_auth_headers).json()
    on = client.get(
        "/api/ml-ventas-ops/sales", params={**ALL_ON, "only_alerts": "true"}, headers=admin_auth_headers
    ).json()

    assert off["facets"]["alerts_total"] == expected
    assert on["facets"]["alerts_total"] == expected


def test_facets_and_kpis_follow_the_same_scope(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _seed_mixed_bag(db)
    params = {**ALL_ON, "only_alerts": "true"}

    listing = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()
    kpis = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()

    assert kpis["groups_count"] == listing["total"]
    assert listing["facets"]["operation_status_total"] == listing["total"]


def test_counter_respects_the_other_filters(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1, metrics="provisional")
    _sale(db, 2, status="cancelled", metrics="provisional")
    db.commit()
    body = client.get(
        "/api/ml-ventas-ops/sales",
        params={**ALL_ON, "include_cancelled": "false"},
        headers=admin_auth_headers,
    ).json()
    assert body["facets"]["alerts_total"] == 1
