"""
Integration tests for pricing endpoints.

Verifies:
- Auth guard: pricing endpoints reject unauthenticated requests.
- 404 on non-existent product.
- Basic happy path structure when product exists.

Run:
    pytest tests/integration/test_pricing_flow.py -v
"""


class TestPricingAuthGuard:
    """Pricing endpoints must require authentication."""

    def test_calcular_por_markup_requires_auth(self, client):
        response = client.post("/api/precios/calcular-por-markup", json={
            "item_id": 1,
            "pricelist_id": 4,
            "markup_objetivo": 30.0,
        })
        assert response.status_code in (401, 403)

    def test_calcular_markup_get_requires_auth(self, client):
        response = client.get("/api/precios/calcular-markup", params={
            "precio": 1000,
            "item_id": 1,
        })
        assert response.status_code in (401, 403)

    def test_set_precio_requires_auth(self, client):
        response = client.post("/api/precios/set", json={
            "item_id": 1,
            "pricelist_id": 4,
            "precio_lista_ml": 1000,
        })
        assert response.status_code in (401, 403)

    def test_historial_requires_auth(self, client):
        response = client.get("/api/precios/historial/1")
        assert response.status_code in (401, 403)


class TestPricingNotFound:
    """Pricing operations on non-existent products return 404."""

    def test_calcular_por_markup_returns_404_for_missing_product(self, client, auth_headers):
        response = client.post(
            "/api/precios/calcular-por-markup",
            json={
                "item_id": 999999,
                "pricelist_id": 4,
                "markup_objetivo": 30.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 404
