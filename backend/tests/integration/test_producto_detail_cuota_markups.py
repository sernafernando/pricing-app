"""
`GET /api/productos/{item_id}` (`obtener_producto`) returns the markup of each
ML instalment price (3/6/9/12 cuotas) like the listing does.

The detail used to hard-code `markup_3_cuotas`..`markup_12_cuotas` to None,
while it already computed every PVP instalment markup. A screen that edits one
product's prices (Publicaciones ML "Precios" tab) reads this endpoint and must
show the same markups Productos shows for the same product.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from unittest.mock import patch

import pytest

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.precio_ml import PrecioML
from app.models.producto import ProductoERP, ProductoPricing

# Force-register ERP stub models (only imported inside endpoint bodies otherwise),
# as test_productos_ppp.py does.
import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401

from tests.integration.test_productos_listing_golden import _FETCH_LIST_COST
from tests.integration.test_productos_tienda_orden import _guard_incompatible_raw_sql as _guard_tienda_raw_sql

CUOTAS = ("3", "6", "9", "12")


@pytest.fixture(autouse=True)
def _ventas_ve_productos(grant_permiso, rol_ventas):
    """GET /productos/{item_id} requires productos.ver (or a price-edit code)."""
    grant_permiso(rol_ventas, "productos.ver")


@pytest.fixture()
def producto_con_cuotas(db) -> ProductoERP:
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    p = ProductoERP(
        item_id=9301,
        codigo="TEST-DETAIL-CUOTAS",
        descripcion="Producto con cuotas",
        costo=100.0,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()
    db.add(
        ProductoPricing(
            item_id=p.item_id,
            precio_lista_ml=1400.0,
            precio_3_cuotas=1500.0,
            precio_6_cuotas=1600.0,
            precio_9_cuotas=1700.0,
            precio_12_cuotas=None,
        )
    )
    db.flush()
    return p


def _guard_incompatible_raw_sql(db):
    """The listing runs two Postgres-only `= ANY(:ids)` lookups unrelated to
    markups (see test_productos_ppp.py); answer them empty on SQLite."""
    original_execute = db.execute

    class _EmptyResult:
        def fetchall(self):
            return []

    def _wrapped(statement, *args, **kwargs):
        sql_text = str(statement)
        if "tienda_nube_productos" in sql_text or "v_ml_catalog_status_latest" in sql_text:
            return _EmptyResult()
        return original_execute(statement, *args, **kwargs)

    db.execute = _wrapped


def test_detail_returns_a_markup_for_each_priced_instalment(client, auth_headers, producto_con_cuotas):
    response = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    for cuota in ("3", "6", "9"):
        assert data[f"markup_{cuota}_cuotas"] is not None, f"markup_{cuota}_cuotas missing: {data}"
    # A higher instalment price over the same cost is a higher markup.
    assert data["markup_3_cuotas"] < data["markup_6_cuotas"] < data["markup_9_cuotas"]
    # No price, no markup.
    assert data["markup_12_cuotas"] is None


def test_detail_instalment_markups_match_the_listing(client, auth_headers, db, producto_con_cuotas):
    _guard_incompatible_raw_sql(db)
    detail = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers).json()
    listing = client.get("/api/productos?page=1&page_size=10", headers=auth_headers).json()["productos"]
    row = next(p for p in listing if p["item_id"] == producto_con_cuotas.item_id)

    for cuota in CUOTAS:
        key = f"markup_{cuota}_cuotas"
        if row[key] is None:
            assert detail[key] is None
        else:
            assert detail[key] == pytest.approx(row[key], abs=0.01), key


@pytest.fixture()
def producto_sin_envio_sobre_tier3(db) -> ProductoERP:
    """A product without ERP shipping whose instalment prices are above monto_tier3
    (33000 without a constants row), in a grupo whose two subcategories have
    different product counts: the grupo-average fallback applies, and the
    listing's average of subcategory averages (2000) differs from an average
    over all products (2500)."""
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.add(SubcategoriaGrupo(subcat_id=9310, grupo_id=1, nombre_subcategoria="Sub A", nombre_categoria="Cat"))
    db.add(SubcategoriaGrupo(subcat_id=9320, grupo_id=1, nombre_subcategoria="Sub B", nombre_categoria="Cat"))
    vecinos = [(9311, 9310, 1000.0), (9321, 9320, 3000.0), (9322, 9320, 3000.0), (9323, 9320, 3000.0)]
    for item_id, subcat, envio in vecinos:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"VECINO-{item_id}",
                descripcion="Vecino con envio",
                costo=1000.0,
                moneda_costo="ARS",
                iva=21.0,
                activo=True,
                envio=envio,
                subcategoria_id=subcat,
            )
        )
    p = ProductoERP(
        item_id=9302,
        codigo="TEST-DETAIL-TIER3",
        descripcion="Producto sin envio sobre tier3",
        costo=20000.0,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
        subcategoria_id=9310,
    )
    db.add(p)
    db.flush()
    db.add(
        ProductoPricing(
            item_id=p.item_id,
            precio_lista_ml=45000.0,
            precio_3_cuotas=50000.0,
            precio_6_cuotas=52000.0,
            precio_9_cuotas=54000.0,
            precio_12_cuotas=56000.0,
            precio_pvp=46000.0,
            precio_pvp_3_cuotas=51000.0,
            precio_pvp_6_cuotas=53000.0,
            precio_pvp_9_cuotas=55000.0,
            precio_pvp_12_cuotas=57000.0,
        )
    )
    db.flush()
    return p


def test_detail_instalment_markups_match_the_listing_with_the_grupo_shipping_fallback(
    client, auth_headers, db, producto_sin_envio_sobre_tier3
):
    _guard_incompatible_raw_sql(db)
    item_id = producto_sin_envio_sobre_tier3.item_id
    detail = client.get(f"/api/productos/{item_id}", headers=auth_headers).json()
    listing = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]
    row = next(p for p in listing if p["item_id"] == item_id)

    for cuota in CUOTAS:
        key = f"markup_{cuota}_cuotas"
        assert row[key] is not None, key
        assert detail[key] == pytest.approx(row[key], abs=0.01), key


def test_a_failing_instalment_markup_is_logged_and_left_empty(
    client, auth_headers, producto_con_cuotas, monkeypatch, caplog
):
    from app.api.endpoints import productos_listing
    from app.services.pricing_context import PricingContext

    def _boom(self, pricelist_id, grupo_id):
        raise ValueError("comision rota")

    # Only the instalment loop resolves commissions through the pricing context.
    monkeypatch.setattr(PricingContext, "comision", _boom)

    with caplog.at_level(logging.DEBUG, logger=productos_listing.logger.name):
        response = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["markup_3_cuotas"] is None
    assert any(
        "comision rota" in record.getMessage() and "3 cuotas" in record.getMessage() for record in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_detail_pvp_markups_match_the_listing_with_the_grupo_shipping_fallback(
    client, auth_headers, db, producto_sin_envio_sobre_tier3
):
    _guard_incompatible_raw_sql(db)
    item_id = producto_sin_envio_sobre_tier3.item_id
    detail = client.get(f"/api/productos/{item_id}", headers=auth_headers).json()
    listing = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]
    row = next(p for p in listing if p["item_id"] == item_id)

    for key in ["markup_pvp"] + [f"markup_pvp_{cuota}_cuotas" for cuota in CUOTAS]:
        assert row[key] is not None, key
        assert detail[key] == pytest.approx(row[key], abs=0.01), key


PVP_KEYS = ["precio_pvp", "markup_pvp"] + [
    f"{kind}_pvp_{cuota}_cuotas" for kind in ("precio", "markup") for cuota in CUOTAS
]


def _detail_and_listing_row(client, auth_headers, db, item_id):
    _guard_incompatible_raw_sql(db)
    detail = client.get(f"/api/productos/{item_id}", headers=auth_headers).json()
    listing = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]
    return detail, next(p for p in listing if p["item_id"] == item_id)


def _assert_same(detail, row, keys):
    for key in keys:
        if row[key] is None:
            assert detail[key] is None, key
        else:
            assert detail[key] == pytest.approx(row[key], abs=0.01), key


def test_detail_pvp_prices_and_markups_follow_precios_ml_like_the_listing(
    client, auth_headers, db, producto_sin_envio_sobre_tier3
):
    """When the product has PVP rows in precios_ml the listing shows THOSE prices
    (the whole PVP set: a list without a row shows no price) and recomputes
    their markups; the detail must show the same."""
    item_id = producto_sin_envio_sobre_tier3.item_id
    db.add(PrecioML(item_id=item_id, pricelist_id=12, precio=60000.0))
    db.add(PrecioML(item_id=item_id, pricelist_id=18, precio=65000.0))
    db.flush()

    detail, row = _detail_and_listing_row(client, auth_headers, db, item_id)

    assert row["precio_pvp"] == 60000.0
    assert row["precio_pvp_6_cuotas"] is None
    _assert_same(detail, row, PVP_KEYS)


def test_detail_ppp_markups_match_the_listing_with_the_grupo_shipping_fallback(
    client, auth_headers, db, producto_sin_envio_sobre_tier3
):
    item_id = producto_sin_envio_sobre_tier3.item_id
    db.add(
        ItemCostListHistory(
            iclh_id=93021,
            coslis_id=1,
            item_id=item_id,
            iclh_price=18000.0,
            iclh_price_aw=18000.0,
            curr_id=1,
            iclh_cd=datetime(2026, 2, 14),
        )
    )
    db.flush()

    detail, row = _detail_and_listing_row(client, auth_headers, db, item_id)

    listing_markups = row["ppp"]["markups"]
    detail_markups = detail["ppp"]["markups"]
    assert "clasica" in listing_markups
    for key, value in listing_markups.items():
        assert detail_markups.get(key) == pytest.approx(value, abs=0.01), key


@pytest.mark.parametrize("target", ["build_pricing_context", "resolver_costos_envio_batch"])
def test_a_failing_markup_input_leaves_markups_empty_and_the_detail_still_answers(
    client, auth_headers, producto_con_cuotas, monkeypatch, caplog, target
):
    from app.api.endpoints import productos_listing

    def _boom(*args, **kwargs):
        raise RuntimeError("sin cotizacion")

    monkeypatch.setattr(productos_listing, target, _boom)

    with caplog.at_level(logging.DEBUG, logger=productos_listing.logger.name):
        response = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["precio_3_cuotas"] == 1500.0
    assert data["markup_3_cuotas"] is None
    assert data["markup_6_cuotas"] is None
    assert any("sin cotizacion" in record.getMessage() for record in caplog.records)


# A product's own extra instalment markup (`markup_adicional_cuotas_custom` / `_pvp_custom`): 0 is a real setting
# ("no extra markup"), only None follows the global one. The detail and the config PATCH used to test the value's
# truth, so a saved 0 came back as None and Productos / Publicaciones ML showed it as "global".


def _con_markup_adicional(db, producto, web, pvp):
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == producto.item_id).one()
    pricing.markup_adicional_cuotas_custom = web
    pricing.markup_adicional_cuotas_pvp_custom = pvp
    db.flush()


def test_detail_returns_a_saved_zero_extra_markup_as_zero(client, auth_headers, db, producto_con_cuotas):
    _con_markup_adicional(db, producto_con_cuotas, 0, 0)

    data = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers).json()

    assert data["markup_adicional_cuotas_custom"] == 0
    assert data["markup_adicional_cuotas_pvp_custom"] == 0


def test_the_productos_listing_returns_a_saved_zero_extra_markup_as_zero(client, auth_headers, db, producto_con_cuotas):
    # Productos' instalment-settings modal starts from the listing row, not from the detail.
    _guard_incompatible_raw_sql(db)
    _con_markup_adicional(db, producto_con_cuotas, 0, None)

    listing = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]

    rows = [p for p in listing if p["item_id"] == producto_con_cuotas.item_id]
    assert len(rows) == 1, f"the product is not once in the listing: {[p['item_id'] for p in listing]}"
    row = rows[0]
    assert row["markup_adicional_cuotas_custom"] == 0
    assert row["markup_adicional_cuotas_pvp_custom"] is None


def test_the_tienda_listing_returns_a_saved_zero_extra_markup_as_zero(client, auth_headers, db, producto_con_cuotas):
    _guard_tienda_raw_sql(db)
    _con_markup_adicional(db, producto_con_cuotas, None, 0)

    with patch(_FETCH_LIST_COST, return_value={}):
        response = client.get("/api/productos/tienda?page=1&page_size=50", headers=auth_headers)

    assert response.status_code == 200, response.text
    rows = [p for p in response.json()["productos"] if p["item_id"] == producto_con_cuotas.item_id]
    assert len(rows) == 1, f"the product is not once in the tienda listing: {response.json()['productos']}"
    assert rows[0]["markup_adicional_cuotas_custom"] is None
    assert rows[0]["markup_adicional_cuotas_pvp_custom"] == 0


def test_detail_keeps_none_for_an_extra_markup_never_set(client, auth_headers, db, producto_con_cuotas):
    _con_markup_adicional(db, producto_con_cuotas, None, 2.5)

    data = client.get(f"/api/productos/{producto_con_cuotas.item_id}", headers=auth_headers).json()

    assert data["markup_adicional_cuotas_custom"] is None
    assert data["markup_adicional_cuotas_pvp_custom"] == 2.5


def test_config_patch_answers_a_saved_zero_extra_markup_as_zero(
    client, auth_headers, db, grant_permiso, rol_ventas, producto_con_cuotas
):
    grant_permiso(rol_ventas, "productos.editar_precio_cuotas")

    response = client.patch(
        f"/api/productos/{producto_con_cuotas.item_id}/config-cuotas",
        json={
            "recalcular_cuotas_auto": None,
            "markup_adicional_cuotas_custom": 0,
            "markup_adicional_cuotas_pvp_custom": 0,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["markup_adicional_cuotas_custom"] == 0
    assert response.json()["markup_adicional_cuotas_pvp_custom"] == 0
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == producto_con_cuotas.item_id).one()
    assert pricing.markup_adicional_cuotas_custom == 0
    assert pricing.markup_adicional_cuotas_pvp_custom == 0
