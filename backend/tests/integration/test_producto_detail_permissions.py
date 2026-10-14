"""`GET /productos/{item_id}` returns a product's prices AND cost, so it is
gated: whoever sees products (productos.ver) or can edit their prices
(pricing.py PERMISOS_EDITAR_PRODUCTOS / PERMISOS_EDITAR_TIENDA) reads it;
any other logged-in user gets 403.

Passing the gate is proven by reaching the handler: 404 for a missing item.
"""

from __future__ import annotations

import pytest

MISSING_ITEM = 987654
URL = f"/api/productos/{MISSING_ITEM}"


def test_a_logged_in_user_without_a_product_code_gets_403(client, auth_headers):
    assert client.get(URL, headers=auth_headers).status_code == 403


def test_an_unrelated_permission_is_not_enough(client, auth_headers, grant_permiso, rol_ventas):
    grant_permiso(rol_ventas, "productos.marcar_color")
    assert client.get(URL, headers=auth_headers).status_code == 403


@pytest.mark.parametrize(
    "codigo",
    [
        "productos.ver",
        "productos.editar_precio_clasica",
        "productos.toggle_rebate",
        "tienda.editar_precio_gremio",
        "tienda.editar_precio_web_transf",
    ],
)
def test_who_sees_products_or_edits_their_prices_passes(client, auth_headers, grant_permiso, rol_ventas, codigo):
    grant_permiso(rol_ventas, codigo)
    response = client.get(URL, headers=auth_headers)
    assert response.status_code == 404, response.text
