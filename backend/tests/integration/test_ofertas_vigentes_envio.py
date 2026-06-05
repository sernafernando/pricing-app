"""
Integration tests for W-2: obtener_ofertas_vigentes uses resolver_costo_envio.

RED phase: drives the fix for the verify-report WARNING that
obtener_ofertas_vigentes still reads raw producto.envio instead of routing
through the central resolver.

Mock pattern mirrors test_productos_detail_envio.py.
Mock target: app.api.endpoints.productos_detail.resolver_costo_envio

Run:
    pytest tests/integration/test_ofertas_vigentes_envio.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.producto import ProductoERP

import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


SENTINEL_ENVIO = 9999.0  # recognisable value that never appears in ERP fixtures


@pytest.fixture()
def producto_ofertas(db) -> ProductoERP:
    """Minimal ProductoERP with a known ERP envio value."""
    p = ProductoERP(
        item_id=9101,
        codigo="TEST-OFERTAS-001",
        descripcion="Producto test ofertas vigentes",
        costo=20000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=300.0,  # stale ERP value — must NOT flow into markup
    )
    db.add(p)
    db.flush()
    return p


class TestOfertasVigentesUsesResolver:
    """
    GET /productos/{id}/ofertas-vigentes must derive costo_envio from
    resolver_costo_envio, not from producto.envio directly.
    """

    def test_ofertas_vigentes_calls_resolver(self, client, auth_headers, producto_ofertas):
        """resolver_costo_envio is called at least once for the product."""
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_ofertas.item_id}/ofertas-vigentes",
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        mock_resolver.assert_called_once()

    def test_ofertas_vigentes_resolver_receives_producto(self, client, auth_headers, producto_ofertas):
        """resolver_costo_envio is called with (db, producto) — not raw envio."""
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_ofertas.item_id}/ofertas-vigentes",
                headers=auth_headers,
            )

        assert response.status_code == 200
        args = mock_resolver.call_args[0]
        # Second positional arg must be the loaded ProductoERP instance
        assert len(args) >= 2
        assert args[1].item_id == producto_ofertas.item_id

    def test_ofertas_vigentes_does_not_use_raw_erp_envio(self, client, auth_headers, producto_ofertas):
        """
        When resolver returns a sentinel value distinct from producto.envio,
        the endpoint must not error (it should use the resolver value, not the
        raw field, in any markup calculations).
        """
        # No publications exist for this item → endpoint returns empty list cleanly.
        # The key assertion is that resolver was called (previous test), and that
        # the endpoint does NOT crash when resolver returns a value != producto.envio.
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=SENTINEL_ENVIO,
        ):
            response = client.get(
                f"/api/productos/{producto_ofertas.item_id}/ofertas-vigentes",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == producto_ofertas.item_id
