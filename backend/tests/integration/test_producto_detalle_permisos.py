"""
GET /productos/{id}/detalle gates each block of fields by the same permission
the product info modal uses to show it:

- productos.ver_info_basica   -> identity fields + who/when last modified
- productos.ver_info_pricing  -> costs, exchange rate, shipping, prices, markups
- productos.ver_info_compras  -> ultimas_compras

The endpoint keeps answering 200 for any authenticated user (the modal fetches
on open for every user and hides all its tabs if the request fails), and
`producto`/`pricing` stay objects so the frontend never reads from null.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tb_supplier import TBSupplier
from tests.conftest import make_access_token

BASICA = "productos.ver_info_basica"
PRICING = "productos.ver_info_pricing"
COMPRAS = "productos.ver_info_compras"

BASIC_FIELDS = ("codigo", "descripcion", "marca", "categoria", "subcategoria_id", "stock")
COST_FIELDS = ("moneda_costo", "costo", "costo_ars", "iva", "costo_envio", "tipo_cambio_usado")
PRICE_FIELDS = (
    "precio_lista_ml",
    "markup",
    "comision_ml_porcentaje",
    "participa_rebate",
    "porcentaje_rebate",
    "out_of_cards",
    "participa_web_transferencia",
    "porcentaje_markup_web",
    "precio_web_transferencia",
    "markup_web_real",
    "precio_3_cuotas",
    "precio_6_cuotas",
    "precio_9_cuotas",
    "precio_12_cuotas",
)
AUDIT_FIELDS = ("usuario_modifico", "fecha_modificacion")


@pytest.fixture()
def producto(db, admin_user) -> ProductoERP:
    p = ProductoERP(
        item_id=9101,
        codigo="PERM-001",
        descripcion="Producto permisos",
        marca="Marca",
        categoria="Categoria",
        subcategoria_id=7,
        stock=4,
        costo=1000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
    )
    db.add(p)
    db.add(
        ProductoPricing(
            item_id=9101,
            precio_lista_ml=2500,
            markup_calculado=30,
            participa_rebate=True,
            porcentaje_rebate=4,
            out_of_cards=True,
            participa_web_transferencia=True,
            porcentaje_markup_web=10,
            precio_web_transferencia=2200,
            markup_web_real=12,
            precio_3_cuotas=2700,
            precio_6_cuotas=2900,
            precio_9_cuotas=3100,
            precio_12_cuotas=3300,
            usuario_id=admin_user.id,
            fecha_modificacion=datetime(2026, 10, 1, 12, 0),
        )
    )
    db.add(TBSupplier(comp_id=1, supp_id=55, supp_name="Proveedor SA"))
    db.add(CommercialTransaction(comp_id=1, ct_transaction=7001, supp_id=55))
    db.add(
        ItemTransaction(
            comp_id=1,
            ct_transaction=7001,
            it_transaction=8001,
            item_id=9101,
            puco_id=10,
            it_cd=datetime(2026, 9, 15, 10, 0),
            it_qty=3,
            it_price=800,
            curr_id=1,
        )
    )
    db.commit()
    return p


def _get(client, user) -> dict:
    with (
        patch("app.api.endpoints.productos_detail.resolver_costo_envio", return_value=150.0),
        patch("app.services.pricing_calculator.obtener_tipo_cambio_actual", return_value=1000.0),
        patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=3),
        patch("app.services.pricing_calculator.obtener_comision_base", return_value=15.5),
    ):
        response = client.get(
            "/api/productos/9101/detalle",
            headers={"Authorization": f"Bearer {make_access_token(user)}"},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_basic(data: dict, visible: bool) -> None:
    for field in BASIC_FIELDS:
        assert (data["producto"][field] is not None) is visible, field
    for field in AUDIT_FIELDS:
        assert (data["pricing"][field] is not None) is visible, field


def _assert_pricing(data: dict, visible: bool) -> None:
    for field in COST_FIELDS:
        assert (data["producto"][field] is not None) is visible, field
    for field in PRICE_FIELDS:
        assert (data["pricing"][field] is not None) is visible, field


def _assert_compras(data: dict, visible: bool) -> None:
    if visible:
        assert data["ultimas_compras"] == [
            {
                "proveedor": "Proveedor SA",
                "fecha": "2026-09-15T10:00:00",
                "cantidad": 3.0,
                "precio_unitario": 800.0,
                "moneda_id": 1,
            }
        ]
    else:
        assert data["ultimas_compras"] == []


def _shape_kept(data: dict) -> None:
    assert data["producto"]["item_id"] == 9101
    assert isinstance(data["pricing"], dict)


def test_no_info_permission_gets_200_with_every_gated_field_hidden(client, active_user, producto):
    data = _get(client, active_user)

    _shape_kept(data)
    _assert_basic(data, False)
    _assert_pricing(data, False)
    _assert_compras(data, False)


def test_basica_only_sees_identity_and_audit(client, active_user, rol_ventas, grant_permiso, producto):
    grant_permiso(rol_ventas, BASICA)

    data = _get(client, active_user)

    _shape_kept(data)
    _assert_basic(data, True)
    assert data["pricing"]["usuario_modifico"] == "Admin User"
    _assert_pricing(data, False)
    _assert_compras(data, False)


def test_pricing_only_sees_costs_and_prices(client, active_user, rol_ventas, grant_permiso, producto):
    grant_permiso(rol_ventas, PRICING)

    data = _get(client, active_user)

    _shape_kept(data)
    _assert_pricing(data, True)
    assert data["producto"]["costo_envio"] == 150.0
    assert data["pricing"]["precio_lista_ml"] == 2500.0
    _assert_basic(data, False)
    _assert_compras(data, False)


def test_compras_only_sees_ultimas_compras(client, active_user, rol_ventas, grant_permiso, producto):
    grant_permiso(rol_ventas, COMPRAS)

    data = _get(client, active_user)

    _shape_kept(data)
    _assert_compras(data, True)
    _assert_basic(data, False)
    _assert_pricing(data, False)


def test_role_with_all_three_sees_everything(client, active_user, rol_ventas, grant_permiso, producto):
    for codigo in (BASICA, PRICING, COMPRAS):
        grant_permiso(rol_ventas, codigo)

    data = _get(client, active_user)

    _assert_basic(data, True)
    _assert_pricing(data, True)
    _assert_compras(data, True)


def test_superadmin_sees_everything(client, rma_superadmin_user, producto):
    data = _get(client, rma_superadmin_user)

    _assert_basic(data, True)
    _assert_pricing(data, True)
    _assert_compras(data, True)


def test_user_override_grants_a_block_the_role_lacks(client, db, active_user, grant_permiso, rol_ventas, producto):
    grant_permiso(rol_ventas, BASICA)
    permiso = Permiso(codigo=COMPRAS, nombre=COMPRAS, descripcion="", categoria="productos", orden=999)
    db.add(permiso)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=True))
    db.commit()

    data = _get(client, active_user)

    _assert_compras(data, True)
    _assert_pricing(data, False)


def test_user_override_revokes_a_block_the_role_has(client, db, active_user, grant_permiso, rol_ventas, producto):
    for codigo in (BASICA, PRICING, COMPRAS):
        grant_permiso(rol_ventas, codigo)
    permiso = db.query(Permiso).filter(Permiso.codigo == PRICING).one()
    db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=False))
    db.commit()

    data = _get(client, active_user)

    _assert_pricing(data, False)
    _assert_basic(data, True)
    _assert_compras(data, True)


def test_unknown_product_still_404(client, active_user):
    response = client.get(
        "/api/productos/424242/detalle",
        headers={"Authorization": f"Bearer {make_access_token(active_user)}"},
    )
    assert response.status_code == 404
