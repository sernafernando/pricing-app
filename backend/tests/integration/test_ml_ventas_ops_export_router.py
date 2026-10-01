"""ODD `ventas-ml-ui-pendiente` T6: `GET /ml-ventas-ops/sales/export` (CSV).

The export must hold EXACTLY what the list holds for the same params -- it
runs the listing itself page by page instead of re-deriving a parallel query.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.models.permiso import Permiso, RolPermisoBase
from app.routers import ml_ventas_ops

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
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


def _sale(db, order_id, *, pack_id=None, status="paid", metrics="ok", nick="comprador", day=1):
    when = NOW.replace(day=day)
    shipping_id = order_id * 10
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            ml_last_updated=when,
            date_created=when,
            seller_id=999,
            total_amount=1234.5,
            paid_amount=1234.5,
            currency_id="ARS",
            shipping_id=shipping_id,
            payment_status="approved",
            buyer_nickname=nick,
        )
    )
    db.add(
        MlShipmentOps(
            shipment_id=shipping_id,
            order_id=order_id,
            status="delivered",
            logistic_type="cross_docking",
            receiver_address={"city": {"name": "Rosario"}, "state": {"name": "Santa Fe"}},
        )
    )
    db.flush()
    db.add(
        MlPaymentOps(
            payment_id=order_id * 10 + 1, order_id=order_id, status="approved", date_approved=when, coupon_amount=10
        )
    )
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=900,
            neto_sin_iva=700,
            iva_reconcilia=True,
            costo_mercaderia=500,
            total_gauss=150,
            markup_pct=30,
            gauss_status=metrics,
            formula_version=1,
            computed_at=NOW,
        )
    )
    db.flush()


def _rows(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_exports_one_row_per_order_with_a_utf8_bom_and_a_filename(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1)
    _sale(db, 2, pack_id=700)
    _sale(db, 3, pack_id=700)
    db.commit()

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"].startswith('attachment; filename="ventas-ml-')
    assert resp.content.startswith(b"\xef\xbb\xbf")
    rows = _rows(resp)
    assert sorted(r["orden"] for r in rows) == ["1", "2", "3"]
    pack_rows = [r for r in rows if r["pack"] == "700"]
    assert len(pack_rows) == 2
    one = next(r for r in rows if r["orden"] == "1")
    assert one["comprador"] == "comprador"
    assert one["importe"] == "1234.50"
    assert one["cupon_ml"] == "10.00"
    assert one["neto"] == "900.00"
    assert one["total_gauss"] == "150.00"
    assert one["markup_pct"] == "30.00"
    assert one["ciudad"] == "Rosario"
    assert one["provincia"] == "Santa Fe"
    assert one["alerta"] == "ok"


def test_holds_exactly_what_the_list_holds_for_the_same_params(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1)
    _sale(db, 2, status="cancelled")
    _sale(db, 3, metrics="provisional")
    _sale(db, 4, pack_id=800)
    _sale(db, 5, pack_id=800, metrics="provisional")
    db.commit()

    for extra in (
        {},
        {"include_cancelled": "false"},
        {"only_alerts": "true"},
        {"only_alerts": "true", "include_cancelled": "false"},
        {"operation_status": "paid"},
    ):
        params = {**ALL_ON, **extra}
        listing = client.get(
            "/api/ml-ventas-ops/sales", params={**params, "limit": 200}, headers=admin_auth_headers
        ).json()
        expected = sorted(str(o["order_id"]) for g in listing["sales"] for o in g["orders"])
        exported = sorted(
            r["orden"]
            for r in _rows(client.get("/api/ml-ventas-ops/sales/export", params=params, headers=admin_auth_headers))
        )
        assert exported == expected, extra


def test_walks_every_page_without_dropping_or_repeating(db, client, admin_auth_headers, rol_admin, monkeypatch):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()

    rows = _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))

    assert sorted(r["orden"] for r in rows) == ["1", "2", "3", "4", "5"]


def test_refuses_a_set_too_big_to_export_and_says_so(db, client, admin_auth_headers, rol_admin, monkeypatch):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_MAX_GROUPS", 2)
    _grant(db, rol_admin)
    for i in range(1, 4):
        _sale(db, i)
    db.commit()

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 422
    assert "Acotá los filtros" in resp.json()["error"]["message"]


def test_neutralises_spreadsheet_formulas_in_free_text(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1, nick='=HYPERLINK("http://evil","x")')
    db.commit()

    rows = _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))

    assert rows[0]["comprador"].startswith("'=")


def test_needs_the_same_permission_as_the_list(db, client, admin_auth_headers):
    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)
    assert resp.status_code == 403


def test_empty_set_is_a_header_only_file(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    db.commit()
    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)
    assert resp.status_code == 200
    assert _rows(resp) == []
    assert resp.content.decode("utf-8-sig").startswith("fecha,orden,pack")
