"""HTTP-level permission gates for the price-writing endpoints.

These endpoints used to depend only on `get_current_user`, so any logged-in
user could rewrite prices even when the Productos/Tienda UI hid the control.
The backend now enforces the same permission set the UI uses to show each
control (frontend audit: Productos.jsx `puedeEditar`, Tienda.jsx
`puedeEditar`, the masivo buttons and the Admin panel route).

Each case runs through the real HTTP stack so the dependency actually runs:
- a user with none of the accepted codes gets 403;
- a user granted exactly one accepted code passes the gate. Passing is
  proven by reaching the handler: 404 for a missing item, 200 for the
  bulk endpoints on an empty table.
"""

from __future__ import annotations

import pytest

from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoPricing

# Productos.jsx: puedeEditar = clasica || cuotas || toggle_rebate || toggle_web_transferencia
PRODUCTOS_EDITAR = (
    "productos.editar_precio_clasica",
    "productos.editar_precio_cuotas",
    "productos.toggle_rebate",
    "productos.toggle_web_transferencia",
)
# Tienda.jsx: puedeEditar = tienda.editar_precio_gremio || tienda.editar_precio_web_transf || cuotas
TIENDA_EDITAR = (
    "tienda.editar_precio_gremio",
    "tienda.editar_precio_web_transf",
    "productos.editar_precio_cuotas",
)
PRODUCTOS_O_TIENDA_EDITAR = tuple(dict.fromkeys(PRODUCTOS_EDITAR + TIENDA_EDITAR))

MISSING_ITEM = 987654

# (case id, url, kwargs for client.post, accepted codes, status once the gate is passed)
CASES = [
    (
        "precios-set",
        "/api/precios/set",
        {"json": {"item_id": MISSING_ITEM, "precio_lista_ml": 1000.0}},
        PRODUCTOS_O_TIENDA_EDITAR,
        404,
    ),
    (
        "precios-set-rapido",
        "/api/precios/set-rapido",
        {"params": {"item_id": MISSING_ITEM, "precio": 1000.0}},
        PRODUCTOS_EDITAR,
        404,
    ),
    (
        "precios-set-cuota",
        "/api/precios/set-cuota",
        {"params": {"item_id": MISSING_ITEM, "tipo_cuota": "3", "precio": 1000.0}},
        PRODUCTOS_O_TIENDA_EDITAR,
        404,
    ),
    (
        "precios-recalcular-cuotas",
        "/api/precios/recalcular-cuotas",
        {"params": {"item_id": MISSING_ITEM}},
        PRODUCTOS_EDITAR,
        404,
    ),
    (
        "productos-recalcular-cuotas-masivo",
        "/api/productos/recalcular-cuotas-masivo",
        {"json": {"lista_tipo": "web"}},
        ("productos.editar_precio_cuotas",),
        200,
    ),
    (
        "productos-calcular-web-masivo",
        "/api/productos/calcular-web-masivo",
        {"json": {"porcentaje_con_precio": 6.0, "porcentaje_sin_precio": 10.0}},
        ("productos.calcular_web_masivo",),
        200,
    ),
    (
        "productos-calcular-pvp-masivo",
        "/api/productos/calcular-pvp-masivo",
        {"json": {"markup_pvp_clasica": 30.0, "adicional_cuotas": 5.0}},
        ("productos.calcular_pvp_masivo",),
        200,
    ),
    ("productos-limpiar-rebate", "/api/productos/limpiar-rebate", {}, ("admin.limpieza_masiva",), 200),
    (
        "productos-limpiar-web-transferencia",
        "/api/productos/limpiar-web-transferencia",
        {},
        ("admin.limpieza_masiva",),
        200,
    ),
]


def _grant(db, rol, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if permiso is None:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria=codigo.split(".")[0], orden=999)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


@pytest.mark.parametrize(("url", "kwargs"), [pytest.param(c[1], c[2], id=c[0]) for c in CASES])
def test_user_without_permission_gets_403(client, auth_headers, url, kwargs) -> None:
    response = client.post(url, headers=auth_headers, **kwargs)

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    ("url", "kwargs", "codigo", "expected"),
    [pytest.param(c[1], c[2], codigo, c[4], id=f"{c[0]}:{codigo}") for c in CASES for codigo in c[3]],
)
def test_user_with_one_accepted_permission_passes_the_gate(
    client, auth_headers, db, rol_ventas, url, kwargs, codigo, expected
) -> None:
    _grant(db, rol_ventas, codigo)
    db.commit()

    response = client.post(url, headers=auth_headers, **kwargs)

    assert response.status_code == expected, response.text


def test_unrelated_permission_does_not_open_price_writes(client, auth_headers, db, rol_ventas) -> None:
    """A Productos permission outside the editing set (e.g. marcar_color) is not enough."""
    _grant(db, rol_ventas, "productos.marcar_color")
    db.commit()

    response = client.post(
        "/api/precios/set-rapido",
        params={"item_id": MISSING_ITEM, "precio": 1000.0},
        headers=auth_headers,
    )

    assert response.status_code == 403, response.text


# --- set-cuota: Tienda codes only cover what the Tienda screen writes -------
# useTiendaPricing.guardarCuota posts /precios/set-cuota with tipo_cuota 3/6/9/12
# and no lista_tipo (default "web"). The clasica price and the PVP list are
# written only from Productos, so a Tienda-only user must not reach them.

TIENDA_ONLY = ("tienda.editar_precio_gremio", "tienda.editar_precio_web_transf")


@pytest.mark.parametrize("codigo", TIENDA_ONLY)
@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"tipo_cuota": "clasica", "lista_tipo": "web"}, id="clasica-web"),
        pytest.param({"tipo_cuota": "3", "lista_tipo": "pvp"}, id="cuota-pvp"),
        pytest.param({"tipo_cuota": "clasica", "lista_tipo": "pvp"}, id="clasica-pvp"),
    ],
)
def test_tienda_only_user_cannot_write_productos_only_set_cuota_fields(
    client, auth_headers, db, rol_ventas, codigo, params
) -> None:
    _grant(db, rol_ventas, codigo)
    db.commit()

    response = client.post(
        "/api/precios/set-cuota",
        params={"item_id": MISSING_ITEM, "precio": 1000.0, **params},
        headers=auth_headers,
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("codigo", TIENDA_ONLY)
def test_tienda_only_user_can_still_save_web_cuotas_like_the_tienda_screen(
    client, auth_headers, db, rol_ventas, codigo
) -> None:
    from tests.integration.test_pricing_manual_origen import _make_producto, _PatchedPricingDeps

    _grant(db, rol_ventas, codigo)
    _make_producto(db, item_id=4101)

    with _PatchedPricingDeps():
        response = client.post(
            "/api/precios/set-cuota",
            params={"item_id": 4101, "tipo_cuota": "6", "precio": 1500.0},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 4101).one()
    assert float(pricing.precio_6_cuotas) == 1500.0


@pytest.mark.parametrize("codigo", PRODUCTOS_EDITAR)
def test_productos_codes_keep_full_set_cuota_access(client, auth_headers, db, rol_ventas, codigo) -> None:
    _grant(db, rol_ventas, codigo)
    db.commit()

    response = client.post(
        "/api/precios/set-cuota",
        params={"item_id": MISSING_ITEM, "tipo_cuota": "clasica", "precio": 1000.0, "lista_tipo": "pvp"},
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text


@pytest.mark.parametrize("url", ["/api/productos/limpiar-rebate", "/api/productos/limpiar-web-transferencia"])
def test_admin_panel_view_permission_alone_cannot_run_bulk_cleanup(client, auth_headers, db, rol_ventas, url) -> None:
    """admin.ver_panel only opens the panel; the bulk cleanup needs admin.limpieza_masiva."""
    _grant(db, rol_ventas, "admin.ver_panel")
    db.commit()

    response = client.post(url, headers=auth_headers)

    assert response.status_code == 403, response.text
