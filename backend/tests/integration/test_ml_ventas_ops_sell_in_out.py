"""Sell in and sell out per sale in the Ventas ML listing (Métricas audit A7).

Each order and each pack of `GET /sales` carries the sell in and sell out the
allocators credited to its item rows (`sell_in_consumos` / `sell_out_consumos`,
canal 'ml', `venta_ref` = `ml_order_items_ops.id`), read through
`sell_in_out_ventas.montos_por_venta` like Ventas fuera ML. Nothing applies ->
null, never zero. The consumption rows are written directly: which sale gets
what is the allocators' business, tested in `tests/services/sell_in/` and
`tests/services/sell_out/`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.producto import ProductoERP
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.models.usuario import Usuario

from .test_ml_ventas_ops_sales_router import _grant_ml_ops_ver, _group_holding, _seed_order
from .test_ml_ventas_ops_tplink_solo import _bg_sessions, catalogo, tp_solo  # noqa: F401 -- fixtures

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
DIA = date(2026, 9, 1)
ITEM = 2964


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


@pytest.fixture()
def mundo(db):
    """The parents a consumption row needs: a product, a sell-in purchase line."""
    usuario = db.query(Usuario).first()
    db.add(ProductoERP(item_id=ITEM, codigo="C2964", descripcion="Router"))
    db.flush()
    compra = SellInCompra(fecha_compra=DIA, moneda="ARS", monto_total=Decimal("1000"), usuario_id=usuario.id)
    db.add(compra)
    db.flush()
    linea = SellInCompraItem(
        compra_id=compra.id, item_id=ITEM, cantidad=10, costo_base_unit=Decimal("1"), monto_asignado=Decimal("1000")
    )
    db.add(linea)
    db.flush()
    return {"usuario_id": usuario.id, "compra_item_id": linea.id}


@pytest.fixture()
def ver(db, rol_admin, mundo):
    _grant_ml_ops_ver(db, rol_admin)
    return mundo


def _venta(db, order_id: int, *, pack_id: int | None = None, items: int = 1) -> list[int]:
    """An order with `items` item rows; returns their ids (the sales' `venta_ref`)."""
    _seed_order(db, order_id, pack_id=pack_id, date_created=SEP_1)
    rows = [
        MlOrderItemOps(order_id=order_id, item_id=f"MLA{order_id}{n}", quantity=1, unit_price=100) for n in range(items)
    ]
    db.add_all(rows)
    db.flush()
    return [row.id for row in rows]


def _sell_in(db, mundo, ref: int, ars: str) -> None:
    db.add(
        SellInConsumo(
            compra_item_id=mundo["compra_item_id"],
            canal="ml",
            venta_ref=ref,
            item_id=ITEM,
            fecha_venta=DIA,
            unidades=1,
            descuento_ars=Decimal(ars),
        )
    )
    db.flush()


def _campana(db, mundo, *, moneda: str = "ARS", tc_modo: str | None = None, tipo_cambio: str | None = None):
    campana = SellOutCampana(
        nombre="Campaña",
        fecha_desde=DIA,
        fecha_hasta=DIA,
        tipo="por_unidad",
        monto_unit=Decimal("5"),
        moneda=moneda,
        tc_modo=tc_modo,
        tipo_cambio=Decimal(tipo_cambio) if tipo_cambio else None,
        usuario_id=mundo["usuario_id"],
    )
    db.add(campana)
    db.flush()
    return campana


def _sell_out(db, campana, ref: int, monto: str, *, tc_venta: str | None = None, canal: str = "ml") -> None:
    db.add(
        SellOutConsumo(
            campana_id=campana.id,
            canal=canal,
            venta_ref=ref,
            item_id=ITEM,
            fecha_venta=DIA,
            unidades=1,
            monto=Decimal(monto),
            tc_venta=Decimal(tc_venta) if tc_venta else None,
        )
    )
    db.flush()


def _listing(db, client, headers) -> dict:
    db.commit()
    response = client.get("/api/ml-ventas-ops/sales", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _order(body: dict, order_id: int) -> dict:
    return next(o for g in body["sales"] for o in g["orders"] if o["order_id"] == order_id)


SELL_FIELDS = ("sell_in_ars", "sell_out_ars", "sell_out_estimado")


class TestPerOrder:
    def test_an_order_carries_the_sum_of_its_item_rows(self, db, client, admin_auth_headers, ver):
        refs = _venta(db, 91001, items=2)
        _sell_in(db, ver, refs[0], "100.50")
        _sell_in(db, ver, refs[1], "20.25")
        campana = _campana(db, ver)
        _sell_out(db, campana, refs[0], "30.00")
        _sell_out(db, campana, refs[1], "12.00")

        order = _order(_listing(db, client, admin_auth_headers), 91001)

        assert order["sell_in_ars"] == pytest.approx(120.75)
        assert order["sell_out_ars"] == pytest.approx(42.00)
        assert order["sell_out_estimado"] is False

    def test_an_order_with_nothing_applied_is_null_never_zero(self, db, client, admin_auth_headers, ver):
        _venta(db, 91002)

        order = _order(_listing(db, client, admin_auth_headers), 91002)

        assert [order[f] for f in SELL_FIELDS] == [None, None, None]

    def test_only_sell_in_leaves_the_sell_out_null(self, db, client, admin_auth_headers, ver):
        refs = _venta(db, 91003)
        _sell_in(db, ver, refs[0], "15.00")

        order = _order(_listing(db, client, admin_auth_headers), 91003)

        assert order["sell_in_ars"] == pytest.approx(15.00)
        assert order["sell_out_ars"] is None
        assert order["sell_out_estimado"] is None

    def test_a_usd_row_converts_at_its_rate_like_the_sell_out_screen(self, db, client, admin_auth_headers, ver):
        refs = _venta(db, 91004)
        campana = _campana(db, ver, moneda="USD", tc_modo="fijo", tipo_cambio="1000")
        _sell_out(db, campana, refs[0], "2.50", tc_venta="1000.123")

        order = _order(_listing(db, client, admin_auth_headers), 91004)

        assert order["sell_out_ars"] == pytest.approx(2500.31)
        assert order["sell_out_estimado"] is False

    def test_a_row_without_its_rate_makes_the_order_sell_out_unknown(self, db, client, admin_auth_headers, ver):
        """MUTATION: summing only the known rows would show a partial sell out as if it were the whole one."""
        refs = _venta(db, 91005, items=2)
        fija = _campana(db, ver, moneda="USD", tc_modo="fijo", tipo_cambio="1000")
        dia_venta = _campana(db, ver, moneda="USD", tc_modo="dia_venta")
        _sell_out(db, fija, refs[0], "1.00", tc_venta="1000")
        _sell_out(db, dia_venta, refs[1], "1.00")

        order = _order(_listing(db, client, admin_auth_headers), 91005)

        assert order["sell_out_ars"] is None
        assert order["sell_out_estimado"] is True

    def test_other_channels_rows_are_not_read(self, db, client, admin_auth_headers, ver):
        refs = _venta(db, 91006)
        _sell_out(db, _campana(db, ver), refs[0], "99.00", canal="fuera")

        order = _order(_listing(db, client, admin_auth_headers), 91006)

        assert order["sell_out_ars"] is None


class TestPerPack:
    def test_a_pack_sums_its_members_and_a_member_without_rows_adds_nothing(self, db, client, admin_auth_headers, ver):
        """Unlike the neto, a member with no sell in is not unknown: nothing applies to it."""
        refs_a = _venta(db, 92001, pack_id=92500)
        _venta(db, 92002, pack_id=92500)
        refs_c = _venta(db, 92003, pack_id=92500)
        _sell_in(db, ver, refs_a[0], "10.00")
        _sell_in(db, ver, refs_c[0], "5.50")
        _sell_out(db, _campana(db, ver), refs_c[0], "7.00")

        group = _group_holding(_listing(db, client, admin_auth_headers), 92001)

        assert group["sell_in_ars"] == pytest.approx(15.50)
        assert group["sell_out_ars"] == pytest.approx(7.00)
        assert group["sell_out_estimado"] is False

    def test_an_unknown_member_sell_out_makes_the_pack_unknown(self, db, client, admin_auth_headers, ver):
        refs_a = _venta(db, 92011, pack_id=92510)
        refs_b = _venta(db, 92012, pack_id=92510)
        _sell_out(db, _campana(db, ver), refs_a[0], "7.00")
        _sell_out(db, _campana(db, ver, moneda="USD", tc_modo="dia_venta"), refs_b[0], "1.00")

        group = _group_holding(_listing(db, client, admin_auth_headers), 92011)

        assert group["sell_out_ars"] is None
        assert group["sell_out_estimado"] is True

    def test_a_pack_with_nothing_applied_is_null(self, db, client, admin_auth_headers, ver):
        _venta(db, 92021, pack_id=92520)
        _venta(db, 92022, pack_id=92520)

        group = _group_holding(_listing(db, client, admin_auth_headers), 92021)

        assert [group[f] for f in SELL_FIELDS] == [None, None, None]


class TestTplinkSolo:
    @pytest.mark.usefixtures("tp_solo")
    def test_a_tp_only_user_gets_no_sell_figure(self, db, client, admin_auth_headers, mundo):
        """Métricas ML denies sell in/out to `tplink.solo`; the TP listing keeps its whitelist."""
        ref = db.query(MlOrderItemOps.id).filter(MlOrderItemOps.order_id == 98002).scalar()
        _sell_in(db, mundo, ref, "10.00")
        _sell_out(db, _campana(db, mundo), ref, "7.00")
        db.commit()

        response = client.get(
            "/api/ml-ventas-ops/sales",
            params={"include_unknown": "true", "include_in_dispute": "true"},
            headers=admin_auth_headers,
        )

        assert response.status_code == 200, response.text
        group = _group_holding(response.json(), 98002)
        for row in (group, _order(response.json(), 98002)):
            assert not set(SELL_FIELDS) & set(row)
