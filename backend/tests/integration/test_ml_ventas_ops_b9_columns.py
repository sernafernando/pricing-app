"""The old Métricas ML operations tab's columns in Ventas ML (Métricas audit B9).

The tab (and its .xlsx) showed, per sale: Costo Unit, Costo Total, Limpio,
Offset Flex, Markup % and Lista, among others. Ventas ML already had the
markup; the listing now also carries the stored cost and net without VAT, each
item its ML listing type, and the CSV export the per-item unit cost, the cost,
the net without VAT, ML's Flex shipping bonus and the listing type. All from
what is already stored (`ml_order_metrics`, `ml_order_item_costos`,
`ml_order_items_ops`), never re-derived. The TP export keeps its columns.
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.routers import ml_ventas_ops
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION

from app.services.order_metrics.store import recompute_order_metrics
from tests.services.ml_ventas_desglose._bonificacion_capture import ORDER_ID as CAPTURE_ORDER_ID
from tests.services.ml_ventas_desglose._bonificacion_capture import seed_capture

from .test_ml_ventas_ops_sales_router import _grant_ml_ops_ver, _group_holding, _seed_order
from .test_ml_ventas_ops_tplink_solo import catalogo, tp_solo  # noqa: F401 -- fixtures

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
ALL_ON = {"include_unknown": "true", "include_in_dispute": "true"}


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


def _venta(
    db,
    order_id: int,
    *,
    pack_id: int | None = None,
    items: tuple = (("MLA1", "gold_special", 2, Decimal("1000.00")),),
    costo: str | None = "2000.00",
    neto_sin_iva: str | None = "4132.23",
) -> None:
    """An order with stored metrics; each item is (mla, listing type, qty, frozen unit cost or None)."""
    _seed_order(db, order_id, pack_id=pack_id, date_created=SEP_1)
    for mla, listing_type, quantity, unit_cost in items:
        db.add(
            MlOrderItemOps(
                order_id=order_id, item_id=mla, quantity=quantity, unit_price=2500, listing_type_id=listing_type
            )
        )
        if unit_cost is not None:
            db.add(
                MlOrderItemCosto(
                    order_id=order_id,
                    item_id=mla,
                    costo_origen=unit_cost,
                    moneda="ARS",
                    costo_unitario_ars=unit_cost,
                    iva_pct=Decimal("21.00"),
                    precio_unitario=Decimal("2500.00"),
                    fuente="sku",
                    producto_item_id=2964,
                )
            )
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("5000.00"),
            neto_sin_iva=Decimal(neto_sin_iva) if neto_sin_iva is not None else None,
            iva_reconcilia=neto_sin_iva is not None,
            costo_mercaderia=Decimal(costo) if costo is not None else None,
            # No cost -> no Total Gauss nor markup (`OrderMetrics`'s invariant).
            total_gauss=Decimal("2132.23") if costo is not None else None,
            markup_pct=Decimal("106.61") if costo is not None else None,
            gauss_status="ok" if costo is not None else "unresolved",
            formula_version=CURRENT_FORMULA_VERSION,
            computed_at=SEP_1,
        )
    )
    db.flush()


def _listing(db, client, headers) -> dict:
    db.commit()
    response = client.get("/api/ml-ventas-ops/sales", params=ALL_ON, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _order(body: dict, order_id: int) -> dict:
    return next(o for g in body["sales"] for o in g["orders"] if o["order_id"] == order_id)


def _export(db, client, headers) -> list[dict]:
    db.commit()
    response = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=headers)
    assert response.status_code == 200, response.text
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))


@pytest.fixture()
def ver(db, rol_admin):
    _grant_ml_ops_ver(db, rol_admin)


@pytest.mark.usefixtures("ver")
class TestListing:
    def test_an_order_carries_its_stored_cost_and_net_without_vat(self, db, client, admin_auth_headers):
        _venta(db, 93001)

        order = _order(_listing(db, client, admin_auth_headers), 93001)

        assert order["costo_mercaderia"] == pytest.approx(2000.00)
        assert order["neto_sin_iva"] == pytest.approx(4132.23)

    def test_unknown_stored_figures_stay_null(self, db, client, admin_auth_headers):
        _venta(db, 93002, costo=None, neto_sin_iva=None)

        order = _order(_listing(db, client, admin_auth_headers), 93002)

        assert order["costo_mercaderia"] is None
        assert order["neto_sin_iva"] is None

    def test_each_item_carries_its_ml_listing_type(self, db, client, admin_auth_headers):
        _venta(db, 93003, items=(("MLA1", "gold_special", 1, None), ("MLA2", "gold_pro", 1, None)))

        order = _order(_listing(db, client, admin_auth_headers), 93003)

        assert [i["listing_type_id"] for i in order["items"]] == ["gold_special", "gold_pro"]

    def test_a_pack_sums_its_members_all_or_nothing(self, db, client, admin_auth_headers):
        _venta(db, 93011, pack_id=93500, costo="100.00", neto_sin_iva="300.00")
        _venta(db, 93012, pack_id=93500, costo="50.50", neto_sin_iva="200.00")
        _venta(db, 93021, pack_id=93510, costo="100.00", neto_sin_iva="300.00")
        _venta(db, 93022, pack_id=93510, costo=None, neto_sin_iva=None)

        body = _listing(db, client, admin_auth_headers)

        known = _group_holding(body, 93011)
        assert (known["costo_mercaderia"], known["neto_sin_iva"]) == (pytest.approx(150.50), pytest.approx(500.00))
        unknown = _group_holding(body, 93021)
        assert (unknown["costo_mercaderia"], unknown["neto_sin_iva"]) == (None, None)


@pytest.mark.usefixtures("ver")
class TestExport:
    def test_the_csv_carries_the_old_tab_figures(self, db, client, admin_auth_headers):
        _venta(
            db,
            93101,
            items=(("MLA1", "gold_special", 2, Decimal("1000.00")), ("MLA2", "gold_pro", 1, Decimal("12.5"))),
            costo="2012.50",
        )

        row = next(r for r in _export(db, client, admin_auth_headers) if r["orden"] == "93101")

        assert row["costo_unitario"] == "1000,00 | 12,50"
        assert row["costo_total"] == "2012,50"
        assert row["neto_sin_iva"] == "4132,23"
        assert row["bonificacion_envio"] == ""
        assert row["tipo_publicacion"] == "Clásica | Premium"

    def test_an_item_without_a_frozen_cost_is_blank_never_zero(self, db, client, admin_auth_headers):
        _venta(db, 93102, items=(("MLA1", "gold_special", 1, Decimal("10.00")), ("MLA2", "free", 1, None)), costo=None)

        row = next(r for r in _export(db, client, admin_auth_headers) if r["orden"] == "93102")

        assert row["costo_unitario"] == "10,00 | "
        assert row["costo_total"] == ""
        assert row["tipo_publicacion"] == "Clásica | free"

    def test_per_item_cells_follow_the_item_rows_not_the_mla(self, db, client, admin_auth_headers):
        """MUTATION: ordering the costs by `item_id` would put MLA1's cost under MLA9."""
        _venta(
            db,
            93103,
            items=(("MLA9", "gold_pro", 1, Decimal("9.00")), ("MLA1", "gold_special", 1, Decimal("1.00"))),
            costo="10.00",
        )

        row = next(r for r in _export(db, client, admin_auth_headers) if r["orden"] == "93103")

        assert row["costo_unitario"] == "9,00 | 1,00"
        assert row["tipo_publicacion"] == "Premium | Clásica"

    def test_the_flex_shipping_bonus_is_exported(self, db, client, admin_auth_headers, monkeypatch):
        seed_capture(db)
        # The capture's real seller, not the fixtures' 999.
        monkeypatch.setattr(settings, "ML_USER_ID", db.get(MlOrdersOps, CAPTURE_ORDER_ID).seller_id)
        recompute_order_metrics(db, [CAPTURE_ORDER_ID])

        row = next(r for r in _export(db, client, admin_auth_headers) if r["orden"] == str(CAPTURE_ORDER_ID))

        assert row["bonificacion_envio"] == "8990,00"

    def test_the_existing_columns_keep_their_place(self):
        assert ml_ventas_ops.EXPORT_HEADER[:22] == [
            "fecha_acreditacion", "fecha_creacion", "orden", "pack", "comprador", "producto", "sku", "cantidad",
            "operacion", "mercaderia", "modo_logistico", "ciudad", "provincia", "moneda", "importe", "cupon_ml",
            "neto", "total_gauss", "markup_pct", "provisorio", "estado_metricas", "alerta",
        ]  # fmt: skip

    def test_the_gauss_extra_columns_are_appended_last(self):
        assert ml_ventas_ops.EXPORT_HEADER_GAUSS_EXTRA == [
            "costo_unitario", "costo_total", "neto_sin_iva", "bonificacion_envio", "tipo_publicacion",
        ]  # fmt: skip

    def test_the_tp_export_keeps_its_columns(self):
        assert ml_ventas_ops.EXPORT_HEADER_TP[17:] == [
            "costo_tp", "total_tp", "markup_tp", "tp_incompleto", "provisorio", "estado_metricas", "alerta",
        ]  # fmt: skip


class TestTplinkSoloExport:
    @pytest.mark.usefixtures("tp_solo")
    def test_every_tp_row_matches_its_header_and_carries_no_cost(self, client, admin_auth_headers):
        response = client.get("/api/ml-ventas-ops/sales/export", params=ALL_ON, headers=admin_auth_headers)

        assert response.status_code == 200, response.text
        lines = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        assert lines[0] == ml_ventas_ops.EXPORT_HEADER_TP
        assert len(lines) > 1
        assert all(len(line) == len(lines[0]) for line in lines[1:])
