"""GET /sell-in/productos/{id}/modos needs `sell_in.ver` as well as the product permission (#1996 verification): the
rows carry typed and frozen unit costs."""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP, TipoMoneda

URL = "/api/sell-in/productos/4512/modos"


@pytest.fixture()
def producto(db) -> None:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()


@pytest.mark.parametrize(
    ("permisos", "esperado"),
    [
        ([], 403),
        (["productos.ver"], 403),
        (["sell_in.ver"], 403),
        (["productos.ver", "sell_in.ver"], 200),
    ],
)
def test_needs_both(client, rol_admin, admin_auth_headers, grant_permiso, producto, permisos, esperado) -> None:
    for codigo in permisos:
        grant_permiso(rol_admin, codigo)
    assert client.get(URL, headers=admin_auth_headers).status_code == esperado


def test_without_a_token_it_is_refused(client, producto) -> None:
    assert client.get(URL).status_code in (401, 403)
