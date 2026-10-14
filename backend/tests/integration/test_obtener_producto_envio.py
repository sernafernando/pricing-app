"""
Integration tests for W-1: obtener_producto resolves shipping centrally.

GET /productos/{item_id} must not read raw producto_erp.envio inside
calcular_limpio: it resolves the real shipping cost through the central
resolver -- the batch form the listing uses, `resolver_costos_envio_batch`,
so detail and listing price the same shipping.

Mock target: app.api.endpoints.productos_listing.resolver_costos_envio_batch

Run:
    pytest tests/integration/test_obtener_producto_envio.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from datetime import date

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.producto import ProductoERP, ProductoPricing
from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    obtener_constantes_pricing,
)

import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


@pytest.fixture(autouse=True)
def _ventas_ve_productos(grant_permiso, rol_ventas):
    """GET /productos/{item_id} requires productos.ver (or a price-edit code)."""
    grant_permiso(rol_ventas, "productos.ver")


SENTINEL_ENVIO = 8888.0  # recognisable; never matches ERP fixture envio


@pytest.fixture()
def producto_single(db) -> ProductoERP:
    """Minimal ProductoERP for the single-product endpoint."""
    p = ProductoERP(
        item_id=9201,
        codigo="TEST-SINGLE-001",
        descripcion="Producto test single endpoint",
        costo=15000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=400.0,  # stale ERP value — must NOT flow raw into calcular_limpio
    )
    db.add(p)
    db.flush()
    db.add(ProductoPricing(item_id=p.item_id, precio_pvp=50000.0))
    db.flush()
    return p


class TestObtenerProductoUsesResolver:
    """
    GET /productos/{item_id} must resolve costo_envio through the central
    batch resolver, not pass producto_erp.envio directly.
    """

    def test_obtener_producto_calls_resolver(self, client, auth_headers, producto_single):
        """The batch resolver is called for the product."""
        with patch(
            "app.api.endpoints.productos_listing.resolver_costos_envio_batch",
            side_effect=lambda db, item_ids, **kw: {item_id: SENTINEL_ENVIO for item_id in item_ids},
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        mock_resolver.assert_called_once()

    def test_obtener_producto_resolver_receives_producto_erp(self, client, auth_headers, producto_single):
        """The batch resolver is called with (db, [item_id])."""
        with patch(
            "app.api.endpoints.productos_listing.resolver_costos_envio_batch",
            side_effect=lambda db, item_ids, **kw: {item_id: SENTINEL_ENVIO for item_id in item_ids},
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        args = mock_resolver.call_args[0]
        assert len(args) >= 2
        assert list(args[1]) == [producto_single.item_id]

    def test_the_resolved_shipping_prices_the_pvp_markup(self, client, auth_headers, db, producto_single):
        """
        The cost the resolver returns (not producto_erp.envio) is the shipping
        the PVP markup is priced with.
        """
        version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
        db.add(version)
        db.flush()
        db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
        db.flush()
        constantes = obtener_constantes_pricing(db)
        comision = calcular_comision_ml_total(50000.0, 12.0, 21.0, constantes=constantes)
        limpio = calcular_limpio(50000.0, 21.0, SENTINEL_ENVIO, comision["comision_total"], constantes=constantes)
        expected = round(calcular_markup(limpio, 15000.0) * 100, 2)

        with patch(
            "app.api.endpoints.productos_listing.resolver_costos_envio_batch",
            side_effect=lambda db, item_ids, **kw: {item_id: SENTINEL_ENVIO for item_id in item_ids},
        ):
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == producto_single.item_id
        assert data["markup_pvp"] == pytest.approx(expected, abs=0.01)
