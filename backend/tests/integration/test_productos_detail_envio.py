"""
Integration tests for T-07: productos_detail uses resolver_costo_envio.

RED phase: these tests drive the integration of envio_real_service into
productos_detail.py. They mock resolver_costo_envio so the mlwebhook DB
is never contacted.

Run:
    pytest tests/integration/test_productos_detail_envio.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.producto import ProductoERP

# Force-register ERP stub models in Base.metadata so Base.metadata.create_all
# includes their tables (they are only imported inside endpoint function bodies
# and would otherwise be absent from the session-level create_all call).
import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


@pytest.fixture()
def producto_base(db) -> ProductoERP:
    """Minimal ProductoERP with ERP envio set to a known value."""
    p = ProductoERP(
        item_id=9001,
        codigo="TEST-ENVIO-001",
        descripcion="Producto test envio",
        costo=10000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=500.0,  # stale ERP value — should be overridden by resolver
    )
    db.add(p)
    db.flush()
    return p


class TestProductoDetailUsesResolver:
    """
    /productos/{id}/detalle must return costo_envio from resolver_costo_envio,
    NOT the raw ProductoERP.envio field.
    """

    def test_detail_uses_real_envio_when_resolver_returns_value(self, client, auth_headers, producto_base):
        """When resolver returns a real cost (e.g. 1200.0), endpoint uses it."""
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=1200.0,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_base.item_id}/detalle",
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["producto"]["costo_envio"] == 1200.0
        mock_resolver.assert_called_once()

    def test_detail_falls_back_to_erp_when_resolver_returns_erp_value(self, client, auth_headers, producto_base):
        """When resolver returns 500.0 (ERP fallback), endpoint reflects it."""
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=500.0,
        ):
            response = client.get(
                f"/api/productos/{producto_base.item_id}/detalle",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["producto"]["costo_envio"] == 500.0

    def test_detail_resolver_called_with_db_and_producto(self, client, auth_headers, producto_base):
        """resolver_costo_envio is called with the db session and the loaded producto."""
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=0.0,
        ) as mock_resolver:
            response = client.get(
                f"/api/productos/{producto_base.item_id}/detalle",
                headers=auth_headers,
            )

        assert response.status_code == 200
        # First positional arg is db (Session), second is producto (ProductoERP)
        args = mock_resolver.call_args[0]
        assert len(args) >= 2
        assert args[1].item_id == producto_base.item_id
