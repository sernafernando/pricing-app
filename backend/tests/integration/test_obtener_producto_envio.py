"""
Integration tests for W-1: obtener_producto uses resolver_costo_envio.

RED phase: drives the fix for the verify-report WARNING that
GET /productos/{item_id} still reads raw producto_erp.envio inside
calcular_limpio calls instead of routing through the central resolver.

Mock target: app.api.endpoints.productos_listing.resolver_costo_envio

Run:
    pytest tests/integration/test_obtener_producto_envio.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.producto import ProductoERP

import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


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
    return p


class TestObtenerProductoUsesResolver:
    """
    GET /productos/{item_id} must resolve costo_envio through
    resolver_costo_envio, not pass producto_erp.envio directly.
    """

    def test_obtener_producto_calls_resolver(self, client, auth_headers, producto_single):
        """resolver_costo_envio is called for the product."""
        with patch(
            "app.api.endpoints.productos_listing.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        mock_resolver.assert_called_once()

    def test_obtener_producto_resolver_receives_producto_erp(self, client, auth_headers, producto_single):
        """resolver_costo_envio is called with (db, producto_erp)."""
        with patch(
            "app.api.endpoints.productos_listing.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        args = mock_resolver.call_args[0]
        assert len(args) >= 2
        assert args[1].item_id == producto_single.item_id

    def test_obtener_producto_does_not_crash_with_sentinel_envio(self, client, auth_headers, producto_single):
        """
        Endpoint must not crash when resolver returns a value != producto_erp.envio.
        The resolved value flows into both calcular_limpio calls (PVP clásica
        and PVP cuotas). No ProductoPricing exists for this fixture, so markup
        fields are None — but the endpoint must return 200.
        """
        with patch(
            "app.api.endpoints.productos_listing.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ):
            response = client.get(
                f"/api/productos/{producto_single.item_id}",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == producto_single.item_id
