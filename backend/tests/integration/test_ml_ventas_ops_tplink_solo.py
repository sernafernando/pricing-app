"""`tplink.solo` on Ventas ML: the TP-only lock, enforced server-side.

A TP-only user sees only the TP store group's sales (the `tplink` clave,
matched on the PUBLICATION's store), costed at the TP cost, and never a Gauss
figure: no Gauss cost, Total Gauss or Gauss markup in any field name or value
of any Ventas ML response or CSV. The Gauss figures are seeded with distinctive
amounts so a leak shows up even under a renamed field.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.routers import ml_ventas_ops
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from tests.integration.test_ml_ventas_ops_sales_router import _order_ids, _seed_order

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
GAUSS = 57997
TPLINK = 2645
TPLINK_NEW = 471846

# Gauss figures: distinctive amounts that must never reach a TP-only user.
TOTAL_GAUSS = Decimal("777.71")
COSTO_GAUSS = Decimal("333.31")
MARKUP_GAUSS = Decimal("233.32")
GAUSS_AMOUNTS = ("777.71", "333.31", "233.32", "777,71", "333,31", "233,32")
SALES_PARAMS = {"include_unknown": "true", "include_in_dispute": "true"}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


@pytest.fixture(autouse=True)
def _bg_sessions(db, monkeypatch):
    @contextmanager
    def _fake():
        session = Session(bind=db.get_bind())
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(ml_ventas_ops, "get_background_db", _fake, raising=False)


def _sale(db, order_id: int, mla: str, *, pack_id: int | None = None, tp: dict | None = None) -> None:
    _seed_order(db, order_id, pack_id=pack_id, date_created=SEP_1)
    db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=1, unit_price=100, title=f"Item {mla}"))
    tp = tp if tp is not None else {"costo_tp": Decimal("300.00"), "total_tp": Decimal("811.02")}
    markup_tp = None
    if tp.get("total_tp") is not None:
        markup_tp = (tp["total_tp"] / tp["costo_tp"] * 100).quantize(Decimal("0.01"))
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("1500.00"),
            neto_sin_iva=Decimal("1239.67"),
            iva_reconcilia=True,
            costo_mercaderia=COSTO_GAUSS,
            total_gauss=TOTAL_GAUSS,
            markup_pct=MARKUP_GAUSS,
            gauss_status="ok",
            formula_version=CURRENT_FORMULA_VERSION,
            computed_at=SEP_1,
            costo_tp=tp.get("costo_tp"),
            total_tp=tp.get("total_tp"),
            markup_tp=markup_tp,
            tp_incompleto=tp.get("tp_incompleto", False),
        )
    )
    db.add(MlVentaDeduccion(order_id=order_id, code="costo_mercaderia", orden=1, monto=COSTO_GAUSS))
    db.flush()


@pytest.fixture()
def catalogo(db, rol_admin, grant_permiso):
    """- 98001: Gauss store
    - 98002: TP-Link store (2645)
    - 98003: TP-Link's new store id (471846), TP cost missing (incomplete)
    - pack 98500 = 98005 + 98006, both TP-Link
    - pack 98600 = 98007, Gauss store"""
    grant_permiso(rol_admin, "ml_ops.ver")
    db.add_all(
        [
            MlTiendaOficial(store_id=TPLINK, nombre="TP-Link", clave="tplink"),
            MlTiendaOficial(store_id=TPLINK_NEW, nombre="TP-Link nueva", clave="tplink"),
            MlTiendaOficial(store_id=GAUSS, nombre="Gauss", clave=None),
        ]
    )
    for mlp_id, mla, store in ((1, "MLA1", GAUSS), (2, "MLA2", TPLINK), (3, "MLA3", TPLINK_NEW)):
        db.add(MercadoLibreItemPublicado(mlp_id=mlp_id, mlp_publicationID=mla, mlp_official_store_id=store))
    _sale(db, 98001, "MLA1")
    _sale(db, 98002, "MLA2")
    _sale(db, 98003, "MLA3", tp={"tp_incompleto": True})
    _sale(db, 98005, "MLA2", pack_id=98500)
    _sale(db, 98006, "MLA2", pack_id=98500)
    _sale(db, 98007, "MLA1", pack_id=98600)
    db.commit()


@pytest.fixture()
def tp_solo(rol_admin, grant_permiso, catalogo):
    grant_permiso(rol_admin, "tplink.solo")


def _gauss_keys(obj) -> list[str]:
    """Every key, at any depth, naming a Gauss figure: anything with `gauss`,
    or a cost/markup field that is not a TP one."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if "gauss" in key or (("markup" in key or "costo" in key) and "tp" not in key):
                found.append(key)
            found += _gauss_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            found += _gauss_keys(value)
    return found


def _assert_no_gauss(resp) -> None:
    assert resp.status_code == 200, resp.text
    assert _gauss_keys(resp.json()) == []
    assert "costo_mercaderia" not in resp.text
    for amount in GAUSS_AMOUNTS:
        assert amount not in resp.text


def _csv_rows(resp) -> list[dict]:
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))


class TestListing:
    def test_only_tp_store_sales_without_any_gauss_figure(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/sales", params=SALES_PARAMS, headers=admin_auth_headers)

        _assert_no_gauss(resp)
        assert sorted(_order_ids(resp.json())) == [98002, 98003, 98005, 98006]

    def test_rows_carry_the_tp_cost_total_and_markup(self, client, admin_auth_headers, tp_solo):
        body = client.get("/api/ml-ventas-ops/sales", params=SALES_PARAMS, headers=admin_auth_headers).json()
        order = next(o for g in body["sales"] for o in g["orders"] if o["order_id"] == 98002)

        assert (order["costo_tp"], order["total_tp"], order["markup_tp"]) == (300.0, 811.02, 270.34)
        assert order["tp_incompleto"] is False
        assert order["neto"] == 1500.0

    def test_incomplete_tp_is_null_with_a_flag_never_zero(self, client, admin_auth_headers, tp_solo):
        body = client.get("/api/ml-ventas-ops/sales", params=SALES_PARAMS, headers=admin_auth_headers).json()
        group = next(g for g in body["sales"] if g["orders"][0]["order_id"] == 98003)
        order = group["orders"][0]

        assert (order["costo_tp"], order["total_tp"], order["markup_tp"], order["tp_incompleto"]) == (
            None,
            None,
            None,
            True,
        )
        assert (group["total_tp"], group["tp_incompleto"]) == (None, True)

    def test_a_pack_sums_its_members_total_tp(self, client, admin_auth_headers, tp_solo):
        body = client.get("/api/ml-ventas-ops/sales", params=SALES_PARAMS, headers=admin_auth_headers).json()
        group = next(g for g in body["sales"] if g["pack_id"] == 98500)

        assert (group["total_tp"], group["tp_incompleto"]) == (1622.04, False)

    def test_a_non_tp_store_filter_returns_nothing(self, client, admin_auth_headers, tp_solo):
        params = {**SALES_PARAMS, "stores": f"{GAUSS},sin_tienda"}
        body = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        assert (body["total"], body["sales"]) == (0, [])

    def test_a_store_filter_is_intersected_never_widened(self, client, admin_auth_headers, tp_solo):
        params = {**SALES_PARAMS, "stores": f"{GAUSS},{TPLINK_NEW}"}
        body = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        assert _order_ids(body) == [98003]

    def test_sorting_by_total_gauss_is_rejected(self, client, admin_auth_headers, tp_solo):
        """The order alone would leak the hidden Gauss totals."""
        params = {**SALES_PARAMS, "sort": "total_gauss"}
        assert client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).status_code == 422

    def test_store_facets_only_show_the_tp_group(self, client, admin_auth_headers, tp_solo):
        params = {**SALES_PARAMS, "stores": str(TPLINK_NEW)}
        facets = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()["facets"]

        assert facets["stores"] == {str(TPLINK): 2, str(TPLINK_NEW): 1}
        assert facets["stores_total"] == 3


class TestKpis:
    def test_kpis_carry_tp_totals_and_no_gauss_figure(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/sales/kpis", params=SALES_PARAMS, headers=admin_auth_headers)

        _assert_no_gauss(resp)
        body = resp.json()
        assert body["groups_count"] == 3
        assert body["orders_count"] == 4
        # 98003 is incomplete: counted, never summed as zero.
        assert body["total_tp_sum"] == pytest.approx(811.02 * 3)
        assert body["tp_incompleto_count"] == 1
        # The incomplete order's pack-of-one is left out of the ratio.
        assert body["markup_tp_weighted_pct"] == pytest.approx(811.02 * 3 / 900 * 100)

    def test_a_non_tp_store_filter_counts_nothing(self, client, admin_auth_headers, tp_solo):
        params = {**SALES_PARAMS, "stores": str(GAUSS)}
        body = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()

        assert (body["groups_count"], body["orders_count"], body["total_tp_sum"]) == (0, 0, 0)


class TestExport:
    def test_csv_has_tp_columns_and_no_gauss_figure(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/sales/export", headers=admin_auth_headers)

        assert resp.status_code == 200
        rows = _csv_rows(resp)
        header = list(rows[0].keys())
        assert not [col for col in header if "gauss" in col or ("markup" in col and "tp" not in col)]
        assert {"costo_tp", "total_tp", "markup_tp", "tp_incompleto"} <= set(header)
        assert sorted(int(r["orden"]) for r in rows) == [98002, 98003, 98005, 98006]
        for amount in GAUSS_AMOUNTS:
            assert amount not in resp.text
        incompleto = next(r for r in rows if r["orden"] == "98003")
        assert (incompleto["total_tp"], incompleto["tp_incompleto"]) == ("", "si")

    def test_a_non_tp_store_filter_exports_no_row(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/sales/export", params={"stores": str(GAUSS)}, headers=admin_auth_headers)

        assert resp.status_code == 200
        assert _csv_rows(resp) == []


class TestDetail:
    def test_order_detail_is_tp_costed_without_gauss(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/orders/98002", headers=admin_auth_headers)

        _assert_no_gauss(resp)
        cadena = resp.json()["cadena_total_tp"]
        assert (cadena["total_tp"], cadena["markup_tp"], cadena["tp_incompleto"]) == (811.02, 270.34, False)
        assert cadena["lineas"] == [
            {"code": "costo_tp", "monto": 300.0, "concepto": None, "prorateado": False},
        ]
        assert resp.json()["total_tp"] == 811.02

    def test_a_gauss_store_order_is_not_found(self, client, admin_auth_headers, tp_solo):
        assert client.get("/api/ml-ventas-ops/orders/98001", headers=admin_auth_headers).status_code == 404

    def test_pack_detail_is_tp_costed_without_gauss(self, client, admin_auth_headers, tp_solo):
        resp = client.get("/api/ml-ventas-ops/packs/98500", headers=admin_auth_headers)

        _assert_no_gauss(resp)
        body = resp.json()
        assert (body["costo_tp"], body["total_tp"], body["tp_incompleto"]) == (600.0, 1622.04, False)
        assert body["markup_tp"] == pytest.approx(270.34)

    def test_a_gauss_store_pack_is_not_found(self, client, admin_auth_headers, tp_solo):
        assert client.get("/api/ml-ventas-ops/packs/98600", headers=admin_auth_headers).status_code == 404


class TestOtherEndpoints:
    def test_divergences_are_forbidden(self, client, admin_auth_headers, tp_solo):
        """Divergence rows carry stored-metric values (Total Gauss among them)."""
        assert client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers).status_code == 403
        assert client.get("/api/ml-ventas-ops/divergences/1", headers=admin_auth_headers).status_code == 403

    def test_resync_of_a_gauss_store_order_is_not_found(
        self, client, admin_auth_headers, rol_admin, grant_permiso, tp_solo, monkeypatch
    ):
        grant_permiso(rol_admin, "ml_ops.resincronizar")

        def _boom(*_args, **_kwargs):
            raise AssertionError("must not resync an order outside the TP group")

        monkeypatch.setattr(ml_ventas_ops, "resync_order", _boom)
        assert client.post("/api/ml-ventas-ops/orders/98001/resync", headers=admin_auth_headers).status_code == 404


class TestWithoutTheLock:
    def test_a_user_without_tplink_solo_still_sees_every_store_and_gauss(self, client, admin_auth_headers, catalogo):
        body = client.get("/api/ml-ventas-ops/sales", params=SALES_PARAMS, headers=admin_auth_headers).json()

        assert sorted(_order_ids(body)) == [98001, 98002, 98003, 98005, 98006, 98007]
        assert body["sales"][0]["orders"][0]["total_gauss"] == float(TOTAL_GAUSS)
        assert "costo_tp" not in json.dumps(body)

    def test_no_tp_store_configured_fails_closed(self, db, client, admin_auth_headers, tp_solo):
        db.query(MlTiendaOficial).filter(MlTiendaOficial.clave == "tplink").delete()
        db.commit()

        assert client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).status_code == 503
