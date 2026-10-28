"""
`GET /api/productos?item_ids=` lists exactly the given products, with every
figure the listing computes for them.

Publicaciones ML shows Productos' price columns (Normal / Cuotas / PVP) for the
products of the page on show: it asks the listing for those products by id, so
the prices and markups are the very ones Productos shows.
"""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP, ProductoPricing

# Force-register ERP stub models (only imported inside endpoint bodies otherwise),
# as test_productos_ppp.py does.
import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401

IDS = (9401, 9402, 9403)


@pytest.fixture(autouse=True)
def _ventas_ve_productos(grant_permiso, rol_ventas):
    grant_permiso(rol_ventas, "productos.ver")


@pytest.fixture()
def productos(db) -> None:
    for item_id in IDS:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"TEST-IDS-{item_id}",
                descripcion=f"Producto {item_id}",
                costo=100.0,
                moneda_costo="ARS",
                iva=21.0,
                activo=True,
                envio=0.0,
            )
        )
        db.flush()
        db.add(ProductoPricing(item_id=item_id, precio_lista_ml=1000.0 + item_id))
    db.flush()


def _guard_incompatible_raw_sql(db):
    """The listing runs two Postgres-only `= ANY(:ids)` lookups unrelated to
    this filter (see test_productos_ppp.py); answer them empty on SQLite."""
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


def _listed(client, auth_headers, query: str):
    response = client.get(f"/api/productos?page=1&page_size=50{query}", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_lists_exactly_the_given_products_with_their_prices(client, auth_headers, db, productos):
    _guard_incompatible_raw_sql(db)
    data = _listed(client, auth_headers, "&item_ids=9401,9403")
    assert sorted(p["item_id"] for p in data["productos"]) == [9401, 9403]
    assert data["total"] == 2
    assert {p["item_id"]: p["precio_lista_ml"] for p in data["productos"]} == {9401: 10401.0, 9403: 10403.0}


def test_without_item_ids_the_listing_is_unchanged(client, auth_headers, db, productos):
    _guard_incompatible_raw_sql(db)
    data = _listed(client, auth_headers, "")
    assert set(IDS) <= {p["item_id"] for p in data["productos"]}


def test_item_ids_combine_with_the_other_filters(client, auth_headers, db, productos):
    _guard_incompatible_raw_sql(db)
    data = _listed(client, auth_headers, "&item_ids=9401,9402&search=TEST-IDS-9402")
    assert [p["item_id"] for p in data["productos"]] == [9402]


@pytest.mark.parametrize("value", ["abc", "9401,x", ",", "", "²", "9401,٣"])
def test_a_value_that_is_not_a_list_of_ids_is_a_422(client, auth_headers, value):
    response = client.get(f"/api/productos?item_ids={value}", headers=auth_headers)
    assert response.status_code == 422, response.text
    assert "item_ids" in response.text


def test_more_ids_than_the_cap_is_a_422(client, auth_headers):
    ids = ",".join(str(i) for i in range(1, 502))
    response = client.get(f"/api/productos?item_ids={ids}", headers=auth_headers)
    assert response.status_code == 422, response.text
    assert "item_ids" in response.text
