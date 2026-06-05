"""
Integration tests for T-09: pricing.py endpoints use resolver_costo_envio.

RED phase — drives T-10 implementation:
- Each endpoint resolves costo_envio once via resolver_costo_envio.
- resolver_costo_envio is called with db + producto (not raw producto.envio).
- IVA is NOT double-divided (calcular_limpio does the /1.21, not the resolver).
- Helpers calcular_markup_rebate / calcular_markup_oferta accept costo_envio param.

Run:
    pytest tests/integration/test_pricing_envio_routing.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.producto import ProductoERP, ProductoPricing


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def producto_ars(db) -> ProductoERP:
    """ARS product with stale ERP envio. Resolver should override it."""
    p = ProductoERP(
        item_id=8001,
        codigo="PRICING-TEST-001",
        descripcion="Producto pricing test",
        costo=50000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=300.0,  # stale ERP value
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def comision_fixtures(db):
    """Minimal pricing constants + commission fixtures for endpoints to work."""
    from app.models.comision_versionada import ComisionVersion, ComisionBase

    from datetime import date

    version = ComisionVersion(
        nombre="Test",
        fecha_desde=date(2000, 1, 1),
        activo=True,
    )
    db.add(version)
    db.flush()

    # Group 1 commission (no pricelist_id column — comision_base is the base rate)
    cb = ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0)
    db.add(cb)
    db.flush()
    return version


# ---------------------------------------------------------------------------
# Tests: resolver is called per endpoint
# ---------------------------------------------------------------------------


class TestPricingEndpointsCallResolver:
    """Each pricing endpoint that loads a producto must call resolver_costo_envio once."""

    def test_calcular_markup_get_calls_resolver(self, client, auth_headers, producto_ars, comision_fixtures):
        """GET /precios/calcular-markup should call resolver_costo_envio once."""
        with patch(
            "app.api.endpoints.pricing.resolver_costo_envio",
            return_value=1500.0,
        ) as mock_res:
            response = client.get(
                "/api/precios/calcular-markup",
                params={"precio": 80000, "item_id": producto_ars.item_id, "pricelist_id": 4},
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        mock_res.assert_called_once()
        # The resolver is called with (db, producto)
        args = mock_res.call_args[0]
        assert args[1].item_id == producto_ars.item_id

    def test_calcular_por_precio_calls_resolver(self, client, auth_headers, producto_ars, comision_fixtures):
        """POST /precios/calcular-por-precio should call resolver_costo_envio once."""
        with patch(
            "app.api.endpoints.pricing.resolver_costo_envio",
            return_value=1500.0,
        ) as mock_res:
            response = client.post(
                "/api/precios/calcular-por-precio",
                json={
                    "item_id": producto_ars.item_id,
                    "pricelist_id": 4,
                    "precio_manual": 80000,
                },
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        mock_res.assert_called_once()

    def test_calcular_completo_calls_resolver_once(self, client, auth_headers, producto_ars, comision_fixtures):
        """POST /precios/calcular-completo should call resolver_costo_envio ONCE (not once per cuota)."""
        with patch(
            "app.api.endpoints.pricing.resolver_costo_envio",
            return_value=1500.0,
        ) as mock_res:
            response = client.post(
                "/api/precios/calcular-completo",
                json={
                    "item_id": producto_ars.item_id,
                    "markup_objetivo": 30.0,
                    "adicional_cuotas": 4.0,
                },
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        # MUST be exactly once — not 5 times (one per pricelist)
        assert mock_res.call_count == 1, f"resolver called {mock_res.call_count} times, expected 1"


class TestPricingHelpersCostoEnvioParam:
    """calcular_markup_rebate and calcular_markup_oferta accept an optional costo_envio param."""

    def test_calcular_markup_rebate_accepts_costo_envio_kwarg(self, db, producto_ars):
        """calcular_markup_rebate must accept costo_envio= without raising TypeError."""
        from app.api.endpoints.pricing import calcular_markup_rebate

        pricing = ProductoPricing(
            item_id=producto_ars.item_id,
            precio_lista_ml=75000,
            participa_rebate=True,
            porcentaje_rebate=3.8,
        )
        db.add(pricing)
        db.flush()

        # Must NOT raise TypeError about unexpected keyword argument
        try:
            calcular_markup_rebate(db, producto_ars, pricing, costo_envio=1500.0)
        except TypeError as exc:
            pytest.fail(f"calcular_markup_rebate raised TypeError: {exc}")

    def test_calcular_markup_oferta_accepts_costo_envio_kwarg(self, db, producto_ars):
        """calcular_markup_oferta must accept costo_envio= without raising TypeError."""
        from app.api.endpoints.pricing import calcular_markup_oferta

        try:
            calcular_markup_oferta(db, producto_ars, costo_envio=1500.0)
        except TypeError as exc:
            pytest.fail(f"calcular_markup_oferta raised TypeError: {exc}")


class TestIVANotDoubleDivided:
    """
    Verifies that IVA is not double-divided.

    Design rule: resolver returns list_cost WITH IVA (as stored in mlwebhook).
    calcular_limpio performs the /1.21 division.
    The endpoint must NOT also divide by 1.21 before passing to calcular_limpio.

    We test this indirectly: when resolver returns X, the limpio calculation
    receives costo_envio=X (not X/1.21).
    """

    def test_calcular_markup_get_passes_raw_resolver_value_to_limpio(
        self, client, auth_headers, producto_ars, comision_fixtures
    ):
        """The raw resolver value (with IVA intact) reaches calcular_limpio."""
        from app.services.pricing_calculator import calcular_limpio as real_limpio

        captured_envio_args: list = []

        def spy_limpio(*args, **kwargs):
            # Third positional arg is costo_envio
            if len(args) >= 3:
                captured_envio_args.append(args[2])
            return real_limpio(*args, **kwargs)

        with patch("app.api.endpoints.pricing.resolver_costo_envio", return_value=1210.0):
            with patch("app.api.endpoints.pricing.calcular_limpio", side_effect=spy_limpio):
                response = client.get(
                    "/api/precios/calcular-markup",
                    params={
                        "precio": 80000,
                        "item_id": producto_ars.item_id,
                        "pricelist_id": 4,
                    },
                    headers=auth_headers,
                )

        assert response.status_code == 200, response.text
        assert captured_envio_args, "calcular_limpio was not called"
        # costo_envio must be 1210.0 (raw), NOT 1000.0 (1210/1.21)
        assert captured_envio_args[0] == 1210.0, f"Expected 1210.0 (no IVA division), got {captured_envio_args[0]}"
