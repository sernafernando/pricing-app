"""ODD `metricas-ml-filtros-dinamicos` T2: the board's `categorias` filter and
the cross-filtered marca / categoría / subcategoría / PM / tienda options.

Every filter narrows EVERY other list (brand -> categories, subcategory ->
brands, PM -> categories, store -> brands, category -> PMs ...) and no list is
narrowed by its own selection. The options come from the rows the board would
show under all the other filters, so period, search and the "solo con ventas"
toggle narrow them too.

"Today" is frozen at 2026-09-30 like the rest of the board tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import URL, _day, _grant, _pub

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
SOLD = date(2026, 9, 20)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture()
def catalog(db, rol_admin):
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
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
    # item, title, marca, categoria, subcategoria, store
    rows = (
        (21, "Epson L3250", "Epson", "Impresoras", 10, 57997),
        (22, "Tinta Epson", "Epson", "Insumos", 20, 2645),
        (23, "HP Laser", "HP", "Impresoras", 10, 57997),
        (24, "Mouse Logitech", "Logitech", "Perifericos", 30, 2645),
    )
    for item_id, title, marca, categoria, subcat, _store in rows:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"SKU-{item_id}",
                descripcion=title,
                marca=marca,
                categoria=categoria,
                subcategoria_id=subcat,
            )
        )
    db.flush()
    for item_id, _title, _marca, _cat, _subcat, store in rows:
        _pub(db, item_id, f"MLA{item_id}", item_id, store)
        _day(db, item_id, f"MLA{item_id}", SOLD, 1, "100", "20", "50")
    db.commit()
    return {"ana": ana.id, "beto": beto.id}


def _get(client, headers, **params):
    resp = client.get(URL, params=params, headers=headers)
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


def test_categorias_filters_the_rows(client, admin_auth_headers, catalog):
    body = _get(client, admin_auth_headers, categorias="insumos")
    assert {row["key"] for row in body["rows"]} == {"22"}
    body = _get(client, admin_auth_headers, categorias="Impresoras,Perifericos")
    assert {row["key"] for row in body["rows"]} == {"21", "23", "24"}
    assert client.get(URL, params={"categorias": "a,,b"}, headers=admin_auth_headers).status_code == 422


def test_without_filters_every_list_offers_everything(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers))
    assert got == {**ALL, "pms": sorted(catalog.values()), "stores": {"57997": 2, "2645": 2}}


def test_brand_narrows_categories_subcategories_pms_and_stores(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, marcas="Epson"))
    assert got["marcas"] == ALL["marcas"]  # its own list is not narrowed
    assert got["categorias"] == ["Impresoras", "Insumos"]
    assert got["subcategorias"] == [10, 20]
    assert got["pms"] == [catalog["ana"]]
    assert got["stores"] == {"57997": 1, "2645": 1}


def test_subcategory_narrows_brands_categories_pms_and_stores(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, subcategorias="10"))
    assert got["marcas"] == ["Epson", "HP"]
    assert got["categorias"] == ["Impresoras"]
    assert got["subcategorias"] == [10, 20, 30]
    assert got["pms"] == sorted(catalog.values())
    assert got["stores"] == {"57997": 2}


def test_pm_narrows_brands_categories_subcategories_and_stores(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, pms=str(catalog["beto"])))
    assert got["marcas"] == ["HP", "Logitech"]
    assert got["categorias"] == ["Impresoras", "Perifericos"]
    assert got["subcategorias"] == [10, 30]
    assert got["pms"] == sorted(catalog.values())
    assert got["stores"] == {"57997": 1, "2645": 1}


def test_store_narrows_brands_categories_subcategories_and_pms(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, stores="2645"))
    assert got["marcas"] == ["Epson", "Logitech"]
    assert got["categorias"] == ["Insumos", "Perifericos"]
    assert got["subcategorias"] == [20, 30]
    assert got["pms"] == sorted(catalog.values())
    assert got["stores"] == {"57997": 2, "2645": 2}  # its own counts keep every store


def test_category_narrows_brands_subcategories_pms_and_stores(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, categorias="Insumos"))
    assert got["marcas"] == ["Epson"]
    assert got["categorias"] == ALL["categorias"]
    assert got["subcategorias"] == [20]
    assert got["pms"] == [catalog["ana"]]
    assert got["stores"] == {"2645": 1}


def test_selections_narrow_each_other_at_once(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, marcas="Epson", stores="2645"))
    assert got["categorias"] == ["Insumos"]
    assert got["subcategorias"] == [20]
    assert got["marcas"] == ["Epson", "Logitech"]  # (store 2645) only
    assert got["stores"] == {"57997": 1, "2645": 1}  # (Epson) only


def test_the_other_board_filters_narrow_the_options_too(client, admin_auth_headers, catalog):
    # The search and the period are part of the universe the lists come from.
    assert _product(_get(client, admin_auth_headers, q="logitech"))["marcas"] == ["Logitech"]
    empty_period = _get(
        client, admin_auth_headers, date_from="2026-08-01", date_to="2026-08-10", solo_con_ventas="true"
    )
    assert _product(empty_period)["marcas"] == []
    # Publications nobody sold in the period are in the universe unless the toggle hides them.
    assert (
        _product(_get(client, admin_auth_headers, date_from="2026-08-01", date_to="2026-08-10"))["marcas"]
        == ALL["marcas"]
    )


def test_the_options_follow_the_grouping_by_publication(client, admin_auth_headers, catalog):
    got = _product(_get(client, admin_auth_headers, group_by="publication", marcas="HP"))
    assert got["categorias"] == ["Impresoras"]
    assert got["subcategorias"] == [10]


def test_a_selected_value_is_still_offered(client, admin_auth_headers, catalog):
    # Logitech never sells Insumos: the board is empty, yet the brand stays offered to untick.
    body = _get(client, admin_auth_headers, marcas="Logitech", categorias="Insumos")
    assert body["rows"] == []
    got = _product(body)
    assert got["marcas"] == ["Epson", "Logitech"]
    assert got["categorias"] == ["Insumos", "Perifericos"]
