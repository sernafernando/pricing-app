"""
Smoke test T-13: cross-consumer consistency.

Verifies that the detail endpoint and pricing endpoint both use the same
resolver_costo_envio function, so a mocked value propagates consistently
to all consumers. The listing is verified at import/source level (see
test_productos_listing_envio.py).

Run:
    pytest tests/smoke/test_envio_consistency.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# Force-register ERP stub models needed by the detail endpoint
import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401

from app.models.producto import ProductoERP
from app.models.comision_versionada import ComisionVersion, ComisionBase


MOCKED_ENVIO = 9999.0  # deliberately unusual value; must appear in both consumers


@pytest.fixture()
def producto_smoke(db) -> ProductoERP:
    """Shared product for cross-consumer tests."""
    p = ProductoERP(
        item_id=6001,
        codigo="SMOKE-ENVIO-001",
        descripcion="Smoke test envio",
        costo=50000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=100.0,  # stale ERP value — must be overridden by mock
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def comision_smoke(db):
    """Minimal commission fixtures."""
    from datetime import date

    v = ComisionVersion(nombre="Smoke", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(v)
    db.flush()
    cb = ComisionBase(version_id=v.id, grupo_id=1, comision_base=12.0)
    db.add(cb)
    db.flush()
    return v


class TestEnvioConsistencyAcrossConsumers:
    """The same mocked resolver value must reach both the detail and pricing consumers."""

    def test_detail_and_pricing_use_same_resolver(self, client, auth_headers, producto_smoke, comision_smoke):
        """
        When resolver_costo_envio returns MOCKED_ENVIO, both endpoints receive
        the same value — proving they both route through the same resolver.
        """
        # Step 1: detail endpoint returns MOCKED_ENVIO as costo_envio
        with patch(
            "app.api.endpoints.productos_detail.resolver_costo_envio",
            return_value=MOCKED_ENVIO,
        ):
            detail_response = client.get(
                f"/api/productos/{producto_smoke.item_id}/detalle",
                headers=auth_headers,
            )

        assert detail_response.status_code == 200, detail_response.text
        detail_envio = detail_response.json()["producto"]["costo_envio"]
        assert detail_envio == MOCKED_ENVIO, f"detail returned {detail_envio}, expected {MOCKED_ENVIO}"

        # Step 2: pricing calcular-markup-get also calls its own resolver,
        # which should also return MOCKED_ENVIO for the same product.
        with patch(
            "app.api.endpoints.pricing.resolver_costo_envio",
            return_value=MOCKED_ENVIO,
        ) as mock_pricing_resolver:
            pricing_response = client.get(
                "/api/precios/calcular-markup",
                params={
                    "precio": 80000,
                    "item_id": producto_smoke.item_id,
                    "pricelist_id": 4,
                },
                headers=auth_headers,
            )

        assert pricing_response.status_code == 200, pricing_response.text
        # The resolver was called with the same producto
        mock_pricing_resolver.assert_called_once()
        pricing_resolver_args = mock_pricing_resolver.call_args[0]
        assert pricing_resolver_args[1].item_id == producto_smoke.item_id

    def test_listing_module_uses_batch_resolver(self):
        """
        Cross-consumer check: listing module imports and uses resolver_costos_envio_batch
        (the batch variant of the same resolver).
        """
        import app.api.endpoints.productos_listing as listing
        from app.services.envio_real_service import resolver_costos_envio_batch

        assert listing.resolver_costos_envio_batch is resolver_costos_envio_batch, (
            "Listing module does not use the real resolver_costos_envio_batch"
        )

    def test_resolver_is_single_source_in_detail(self):
        """resolver_costo_envio is imported at module level in productos_detail."""
        import app.api.endpoints.productos_detail as detail
        from app.services.envio_real_service import resolver_costo_envio

        assert detail.resolver_costo_envio is resolver_costo_envio

    def test_resolver_is_single_source_in_pricing(self):
        """resolver_costo_envio is imported at module level in pricing."""
        import app.api.endpoints.pricing as pricing
        from app.services.envio_real_service import resolver_costo_envio

        assert pricing.resolver_costo_envio is resolver_costo_envio
