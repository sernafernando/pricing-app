"""
Integration tests for ML sync endpoints.

Verifies:
- Auth guard: sync endpoints reject unauthenticated requests.
- Authenticated users can reach the endpoint (response shape).

Run:
    pytest tests/integration/test_sync_ml_flow.py -v
"""


class TestSyncMLAuthGuard:
    """ML sync endpoints must require authentication."""

    def test_sync_precios_requires_auth(self, client):
        response = client.post("/api/sync-ml/precios")
        assert response.status_code in (401, 403)

    def test_listar_listas_requires_auth(self, client):
        response = client.get("/api/sync-ml/listas")
        assert response.status_code in (401, 403)


class TestSyncMLAuthenticated:
    """ML sync endpoints respond correctly to authenticated requests."""

    def test_listar_listas_returns_pricelists(self, client, auth_headers):
        response = client.get("/api/sync-ml/listas", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert "listas" in body
