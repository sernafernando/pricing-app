"""ODD `ventas-ml-ui-pendiente` T6: `GET /ml-ventas-ops/sales/export` (CSV).

The export must hold EXACTLY what the list holds for the same params -- it
runs the listing itself page by page instead of re-deriving a parallel query.
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
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


@pytest.fixture(autouse=True)
def bg_sessions(db, monkeypatch):
    """Stands in for `get_background_db` (a real `SessionLocal` would not see
    the test transaction) and records every short session the export opens.

    Each short session is a DISTINCT `Session` bound to the test's connection
    (same uncommitted data, different object), so a regression that hands the
    request `db` to the page work is detectable by identity."""
    events = {"open": 0, "close": 0, "max_open": 0, "sessions": [], "fail_on_open": None, "on_open": None}

    @contextmanager
    def _fake():
        events["open"] += 1
        if events["on_open"] is not None:
            # A hook to change the data BETWEEN pages, as a concurrent sale or
            # metrics recompute would.
            events["on_open"](events["open"])
        if events["fail_on_open"] is not None and events["open"] >= events["fail_on_open"]:
            events["close"] += 1
            raise RuntimeError("pool timeout")
        events["max_open"] = max(events["max_open"], events["open"] - events["close"])
        session = Session(bind=db.get_bind())
        events["sessions"].append(session)
        try:
            yield session
        finally:
            session.close()
            events["close"] += 1

    monkeypatch.setattr(ml_ventas_ops, "get_background_db", _fake, raising=False)
    return events


def _grant(db, rol_admin):
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(codigo="ml_ops.ver", nombre="Ver", descripcion="", categoria="ml_ops", orden=200)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _sale(db, order_id, *, pack_id=None, status="paid", metrics="ok", nick="comprador", day=1, accredited_day=None):
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
            payment_id=order_id * 10 + 1,
            order_id=order_id,
            status="approved",
            date_approved=NOW.replace(day=accredited_day or day),
            coupon_amount=10,
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
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


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
    assert one["importe"] == "1234,50"
    assert one["cupon_ml"] == "10,00"
    assert one["neto"] == "900,00"
    assert one["total_gauss"] == "150,00"
    assert one["markup_pct"] == "30,00"
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
    assert resp.content.decode("utf-8-sig").startswith("fecha_acreditacion;fecha_creacion;orden;pack")


def _item(db, order_id, title, sku, qty):
    db.add(
        MlOrderItemOps(
            order_id=order_id, item_id=f"MLA{order_id}{qty}", title=title, seller_sku=sku, quantity=qty, unit_price=10
        )
    )
    db.flush()


def test_exports_the_product_joining_several_items_never_dropping_one(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1)
    _item(db, 1, "Router TP-Link", "TPL-1", 2)
    _item(db, 1, "Cable UTP", "UTP-5", 3)
    _sale(db, 2)
    db.commit()

    rows = {
        r["orden"]: r
        for r in _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))
    }

    assert rows["1"]["producto"] == "Router TP-Link | Cable UTP"
    assert rows["1"]["sku"] == "TPL-1 | UTP-5"
    assert rows["1"]["cantidad"] == "2 | 3"
    assert rows["2"]["producto"] == ""


def test_product_titles_get_the_formula_guard_too(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1)
    _item(db, 1, "=cmd|' /C calc'!A0", "+SKU", 1)
    db.commit()

    row = _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))[0]

    assert row["producto"].startswith("'=")
    assert row["sku"].startswith("'+")


def test_the_day_is_the_accreditation_day_not_the_creation_day(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1, day=3, accredited_day=9)
    # A pack's day is its LAST member's accreditation (same MAX rule as the list).
    _sale(db, 2, pack_id=600, day=3, accredited_day=4)
    _sale(db, 3, pack_id=600, day=3, accredited_day=12)
    db.commit()

    rows = {
        r["orden"]: r
        for r in _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))
    }

    assert rows["1"]["fecha_acreditacion"].startswith("2026-09-09")
    assert rows["1"]["fecha_creacion"].startswith("2026-09-03")
    assert rows["2"]["fecha_acreditacion"].startswith("2026-09-12")
    assert rows["3"]["fecha_acreditacion"].startswith("2026-09-12")


def test_each_page_runs_in_its_own_short_session_never_the_request_one(
    db, client, admin_auth_headers, rol_admin, monkeypatch, bg_sessions
):
    # 5 groups / 2 per page = 3 pages. A streaming response outlives the
    # request handler: holding the request session for all of it pins a pooled
    # connection while the client downloads (QueuePool incident, PR #811).
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert bg_sessions["open"] == 3
    assert bg_sessions["close"] == 3
    assert bg_sessions["max_open"] == 1


def test_export_pages_skip_the_facets_and_the_alert_counter(
    db, client, admin_auth_headers, rol_admin, monkeypatch, query_counter
):
    _grant(db, rol_admin)
    _sale(db, 1)
    _sale(db, 2, pack_id=700)
    _sale(db, 3, pack_id=700)
    db.commit()
    alert_counts = []
    real = ml_ventas_ops.alert_groups_count
    monkeypatch.setattr(ml_ventas_ops, "alert_groups_count", lambda scope: alert_counts.append(1) or real(scope))

    with query_counter() as listing:
        assert client.get("/api/ml-ventas-ops/sales", params=ALL_ON, headers=admin_auth_headers).status_code == 200
    assert alert_counts == [1]  # control: the listing DOES count alerts
    assert any(" as bucket" in st for st in listing.statements)  # control: and DOES run the facets
    alert_counts.clear()

    with query_counter() as export:
        resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert sorted(r["orden"] for r in _rows(resp)) == ["1", "2", "3"]
    assert alert_counts == []
    assert not any(" as bucket" in st for st in export.statements)


def test_no_export_page_runs_the_total_count(db, client, admin_auth_headers, rol_admin, monkeypatch, query_counter):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()

    def totals(statements):
        return [st for st in statements if "count(distinct" in st and "group by" not in st]

    with query_counter() as one_page:
        monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 200)
        client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    with query_counter() as three_pages:
        resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert len(_rows(resp)) == 5
    # The total is the length of the ordered key list the export fixes up
    # front: no page (not even the first) runs the distinct-count query.
    assert totals(one_page.statements) == []
    assert totals(three_pages.statements) == []


def test_the_request_session_is_closed_before_the_first_byte_streams(
    db, client, admin_auth_headers, rol_admin, monkeypatch, bg_sessions
):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()
    timeline = []
    real_close = db.close
    monkeypatch.setattr(db, "close", lambda: (timeline.append(("request_close", bg_sessions["open"])), real_close())[1])

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert len(_rows(resp)) == 5
    # Closed once the first page was read (1 short session so far), never
    # later, i.e. before page 2's session opens.
    assert timeline and timeline[0] == ("request_close", 1)


def test_the_page_work_runs_on_the_short_session_not_the_request_one(
    db, client, admin_auth_headers, rol_admin, monkeypatch, bg_sessions
):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()
    used = {"sales_page": [], "dates": []}
    real_page = ml_ventas_ops._sales_page
    real_dates = ml_ventas_ops.member_accreditation_dates
    monkeypatch.setattr(
        ml_ventas_ops, "_sales_page", lambda s, *a, **k: used["sales_page"].append(s) or real_page(s, *a, **k)
    )
    monkeypatch.setattr(
        ml_ventas_ops,
        "member_accreditation_dates",
        lambda s, *a, **k: used["dates"].append(s) or real_dates(s, *a, **k),
    )

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    # The ordered key list + 3 pages built by key; dates once per page.
    assert len(used["sales_page"]) == 4 and len(used["dates"]) == 3
    for s in used["sales_page"] + used["dates"]:
        assert s is not db
        assert any(s is opened for opened in bg_sessions["sessions"])


def test_a_page_that_fails_mid_stream_ends_the_file_with_an_explicit_error_line(
    db, client, admin_auth_headers, rol_admin, monkeypatch, bg_sessions
):
    # Page 1 is fetched before the 200; pages 2+ open their session inside the
    # stream, after the header went out: a failure there cannot change the
    # status, so the file itself must say it is incomplete.
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()
    bg_sessions["fail_on_open"] = 2

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    lines = resp.content.decode("utf-8-sig").splitlines()
    assert lines[-1] == "# ERROR: exportación incompleta — 2 de 5 ventas exportadas. Volvé a intentar."
    assert sum(1 for line in lines[1:-1]) == 2  # only page 1's rows precede it


def test_a_complete_export_has_no_error_line(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin)
    _sale(db, 1)
    db.commit()
    text = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers).content.decode(
        "utf-8-sig"
    )
    assert "# ERROR" not in text


def test_a_change_between_pages_never_repeats_or_drops_a_sale(
    db, client, admin_auth_headers, rol_admin, monkeypatch, bg_sessions
):
    """The export fixes its ORDERED list of groups in its first short
    transaction and then fetches each page BY KEY. Paging by OFFSET over a
    fresh query per page let a change between pages reorder the set: here
    sale 1 becomes the newest after page 1 was written, which under OFFSET
    repeated sale 4 and dropped sale 1."""
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 6):
        _sale(db, i, day=i)
    db.commit()

    def move_sale_1_to_the_top(opened: int) -> None:
        if opened == 2:
            db.query(MlPaymentOps).filter_by(order_id=1).update({"date_approved": NOW.replace(day=28)})
            db.flush()

    bg_sessions["on_open"] = move_sale_1_to_the_top

    rows = _rows(client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers))

    assert [r["orden"] for r in rows] == ["5", "4", "3", "2", "1"]


def test_an_empty_scope_with_data_elsewhere_is_a_header_only_file(db, client, admin_auth_headers, rol_admin):
    """Sales exist, none match: page 1 is built from an EMPTY key list (no
    empty `IN ()`, no `LIMIT 0` error) and the file is just the header."""
    _grant(db, rol_admin)
    _sale(db, 1)
    db.commit()

    resp = client.get(
        "/api/ml-ventas-ops/sales/export", params={**ALL_ON, "q": "no-existe-nada"}, headers=admin_auth_headers
    )

    assert resp.status_code == 200
    lines = resp.content.decode("utf-8-sig").splitlines()
    assert len(lines) == 1 and lines[0].startswith("fecha_acreditacion;")


def test_exactly_the_cap_exports_every_sale(db, client, admin_auth_headers, rol_admin, monkeypatch):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_MAX_GROUPS", 3)
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_PAGE_SIZE", 2)
    _grant(db, rol_admin)
    for i in range(1, 4):
        _sale(db, i, day=i)
    db.commit()

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert [r["orden"] for r in _rows(resp)] == ["3", "2", "1"]


def test_one_over_the_cap_is_422_with_the_reason(db, client, admin_auth_headers, rol_admin, monkeypatch):
    monkeypatch.setattr(ml_ventas_ops, "EXPORT_MAX_GROUPS", 3)
    _grant(db, rol_admin)
    for i in range(1, 5):
        _sale(db, i, day=i)
    db.commit()

    resp = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == (
        "Son más de 3 ventas, demasiadas para exportar de una vez. "
        "Acotá los filtros, por ejemplo con un rango de fechas."
    )
