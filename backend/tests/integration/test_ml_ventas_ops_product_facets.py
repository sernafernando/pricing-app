"""ODD `metricas-ml-filtros-dinamicos` T3: Ventas ML's `categorias` filter and
the cross-filtered marca / categoría / subcategoría / PM / tienda options.

Same contract as the Métricas ML board: every filter narrows EVERY other list
(in both directions) and never its own. The lists come from the groups the
listing would show under all the OTHER filters (period, search, status,
switches, store), through the items of every member of those groups.
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.routers import ml_ventas_ops
from tests.integration.test_ml_ventas_ops_sales_router import _grant_ml_ops_ver, _order_ids, _seed_order

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
SALES = "/api/ml-ventas-ops/sales"
GAUSS, TPLINK = 57997, 2645


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


def _sell(db, order_id: int, product: int, store: int, *, pack_id=None, status="paid") -> None:
    mla = f"MLA{order_id}"
    _seed_order(db, order_id, date_created=SEP_1, pack_id=pack_id, status=status)
    db.add(MercadoLibreItemPublicado(mlp_id=order_id, mlp_publicationID=mla, mlp_official_store_id=store))
    db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=1, unit_price=100, title=f"Item {mla}"))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=mla,
            variation_id=None,
            costo_origen=100,
            moneda="ARS",
            costo_unitario_ars=100,
            iva_pct=21,
            precio_unitario=150,
            fuente="test",
            producto_item_id=product,
        )
    )
    db.flush()


@pytest.fixture()
def catalog(db, rol_admin):
    _grant_ml_ops_ver(db, rol_admin)
    ana = Usuario(username="ana", email="ana@x.com", nombre="Ana", password_hash="x", activo=True)
    beto = Usuario(username="beto", email="beto@x.com", nombre="Beto", password_hash="x", activo=True)
    db.add_all([ana, beto])
    db.flush()
    db.add_all(
        [
            MarcaPM(marca="Epson", categoria="Impresoras", usuario_id=ana.id),
            MarcaPM(marca="Epson", categoria="Insumos", usuario_id=ana.id),
            MarcaPM(marca="HP", categoria="Impresoras", usuario_id=beto.id),
            MarcaPM(marca="Logitech", categoria="Perifericos", usuario_id=beto.id),
        ]
    )
    for subcat_id, nombre, categoria in (
        (10, "Laser", "Impresoras"),
        (20, "Toner", "Insumos"),
        (30, "Mouse", "Perifericos"),
    ):
        db.add(
            SubcategoriaGrupo(subcat_id=subcat_id, nombre_subcategoria=nombre, nombre_categoria=categoria, grupo_id=1)
        )
    products = (
        (21, "Epson", "Impresoras", 10),
        (22, "Epson", "Insumos", 20),
        (23, "HP", "Impresoras", 10),
        (24, "Logitech", "Perifericos", 30),
    )
    for item_id, marca, categoria, subcat in products:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"S{item_id}",
                descripcion=f"P{item_id}",
                marca=marca,
                categoria=categoria,
                subcategoria_id=subcat,
            )
        )
    db.flush()
    _sell(db, 98001, 21, GAUSS)
    _sell(db, 98002, 22, TPLINK)
    _sell(db, 98003, 23, GAUSS)
    _sell(db, 98004, 24, TPLINK)
    db.commit()
    return {"ana": ana.id, "beto": beto.id}


def _get(client, headers, **params):
    resp = client.get(SALES, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _product(body):
    p = body["facets"]["product"]
    return {
        "marcas": p["marcas"],
        "categorias": p["categorias"],
        "subcategorias": sorted(s["id"] for g in p["subcategorias"] for s in g["subcategorias"]),
        "pms": sorted(x["id"] for x in p["pms"]),
        "stores": body["facets"]["stores"],
    }


ALL = {
    "marcas": ["Epson", "HP", "Logitech"],
    "categorias": ["Impresoras", "Insumos", "Perifericos"],
    "subcategorias": [10, 20, 30],
}


class TestCategoriaFilter:
    def test_filters_the_listing_case_insensitively(self, client, admin_auth_headers, catalog):
        assert _order_ids(_get(client, admin_auth_headers, categorias="insumos")) == [98002]
        both = _get(client, admin_auth_headers, categorias="Impresoras,Perifericos")
        assert sorted(_order_ids(both)) == [98001, 98003, 98004]

    def test_a_pack_comes_back_whole_when_one_item_matches(self, db, client, admin_auth_headers, catalog):
        _sell(db, 98010, 22, TPLINK, pack_id=98500)
        _sell(db, 98011, 24, TPLINK, pack_id=98500)
        db.commit()
        body = _get(client, admin_auth_headers, categorias="Insumos")
        assert sorted(_order_ids(body)) == [98002, 98010, 98011]

    def test_one_item_must_satisfy_every_product_facet(self, db, client, admin_auth_headers, catalog):
        # Epson (item 21) + Perifericos (item 24) live in DIFFERENT items of one pack: no match.
        _sell(db, 98020, 21, GAUSS, pack_id=98600)
        _sell(db, 98021, 24, GAUSS, pack_id=98600)
        db.commit()
        body = _get(client, admin_auth_headers, marcas="Epson", categorias="Perifericos")
        assert _order_ids(body) == []

    def test_kpis_and_export_read_the_same_param(self, client, admin_auth_headers, catalog):
        # include_unknown: these seeded orders have no shipment, which the KPI defaults hide.
        kpis = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"categorias": "Insumos", "include_unknown": "true"},
            headers=admin_auth_headers,
        )
        assert kpis.status_code == 200
        assert kpis.json()["groups_count"] == 1
        export = client.get(
            "/api/ml-ventas-ops/sales/export", params={"categorias": "Insumos"}, headers=admin_auth_headers
        )
        assert export.status_code == 200
        rows = list(csv.reader(io.StringIO(export.text.lstrip("﻿")), delimiter=";"))
        assert len(rows) == 2  # header + the one sale

    @pytest.mark.parametrize("bad", ["a,,b", ","])
    def test_an_empty_entry_is_422(self, client, admin_auth_headers, catalog, bad):
        assert client.get(SALES, params={"categorias": bad}, headers=admin_auth_headers).status_code == 422


class TestCrossFilteredOptions:
    def test_without_filters_every_list_offers_everything(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers))
        assert got == {**ALL, "pms": sorted(catalog.values()), "stores": {"57997": 2, "2645": 2}}

    def test_brand_narrows_categories_subcategories_pms_and_stores(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, marcas="Epson"))
        assert got["marcas"] == ALL["marcas"]  # its own list is not narrowed
        assert got["categorias"] == ["Impresoras", "Insumos"]
        assert got["subcategorias"] == [10, 20]
        assert got["pms"] == [catalog["ana"]]
        assert got["stores"] == {"57997": 1, "2645": 1}

    def test_subcategory_narrows_brands_categories_pms_and_stores(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, subcategorias="10"))
        assert got["marcas"] == ["Epson", "HP"]
        assert got["categorias"] == ["Impresoras"]
        assert got["subcategorias"] == [10, 20, 30]
        assert got["pms"] == sorted(catalog.values())
        assert got["stores"] == {"57997": 2}

    def test_pm_narrows_brands_categories_subcategories_and_stores(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, pms=str(catalog["beto"])))
        assert got["marcas"] == ["HP", "Logitech"]
        assert got["categorias"] == ["Impresoras", "Perifericos"]
        assert got["subcategorias"] == [10, 30]
        assert got["pms"] == sorted(catalog.values())
        assert got["stores"] == {"57997": 1, "2645": 1}

    def test_store_narrows_brands_categories_subcategories_and_pms(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, stores=str(TPLINK)))
        assert got["marcas"] == ["Epson", "Logitech"]
        assert got["categorias"] == ["Insumos", "Perifericos"]
        assert got["subcategorias"] == [20, 30]
        assert got["pms"] == sorted(catalog.values())
        assert got["stores"] == {"57997": 2, "2645": 2}  # its own counts keep every store

    def test_category_narrows_brands_subcategories_pms_and_stores(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, categorias="Insumos"))
        assert got["marcas"] == ["Epson"]
        assert got["categorias"] == ALL["categorias"]
        assert got["subcategorias"] == [20]
        assert got["pms"] == [catalog["ana"]]
        assert got["stores"] == {"2645": 1}

    def test_selections_narrow_each_other_at_once(self, client, admin_auth_headers, catalog):
        got = _product(_get(client, admin_auth_headers, marcas="Epson", stores=str(TPLINK)))
        assert got["categorias"] == ["Insumos"]
        assert got["subcategorias"] == [20]
        assert got["marcas"] == ["Epson", "Logitech"]
        assert got["stores"] == {"57997": 1, "2645": 1}

    def test_the_other_filters_narrow_the_options_too(self, db, client, admin_auth_headers, catalog):
        # The search, the period and the switches are part of the universe the lists come from.
        assert _product(_get(client, admin_auth_headers, q="MLA98004"))["marcas"] == ["Logitech"]
        assert _product(_get(client, admin_auth_headers, date_from="2026-08-01", date_to="2026-08-10"))["marcas"] == []
        _sell(db, 98030, 23, GAUSS, status="cancelled")
        _sell(db, 98031, 24, TPLINK, status="cancelled")
        db.commit()
        hidden = _get(client, admin_auth_headers, include_cancelled="false", stores=str(GAUSS))
        assert _product(hidden)["marcas"] == ["Epson", "HP"]

    def test_the_options_come_from_every_member_of_a_matching_pack(self, db, client, admin_auth_headers, catalog):
        _sell(db, 98040, 21, GAUSS, pack_id=98700)
        _sell(db, 98041, 24, GAUSS, pack_id=98700)
        db.commit()
        # The search finds the Epson order only, but the pack comes back whole: its
        # Logitech sibling is part of the row the operator sees, so it is offered too.
        got = _product(_get(client, admin_auth_headers, q="MLA98040"))
        assert got["marcas"] == ["Epson", "Logitech"]
        # Within the pack the item-level rule still holds: Epson + Perifericos is no item.
        both = _product(_get(client, admin_auth_headers, q="MLA98040", marcas="Epson"))
        assert both["categorias"] == ["Impresoras"]

    def test_a_selected_value_is_still_offered(self, client, admin_auth_headers, catalog):
        body = _get(client, admin_auth_headers, marcas="Logitech", categorias="Insumos")
        assert _order_ids(body) == []
        got = _product(body)
        assert got["marcas"] == ["Epson", "Logitech"]
        assert got["categorias"] == ["Insumos", "Perifericos"]
