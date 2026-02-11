"""
Smoke tests: verify the FastAPI app starts and core endpoints respond.

These tests are intentionally lightweight — they confirm the application
can be imported, the ASGI app can be instantiated, and non-DB endpoints
return expected responses.

Run:
    pytest tests/smoke/ -v
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoints:
    """Verify application liveness and readiness."""

    def test_root_returns_api_info(self) -> None:
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "running"
        assert "version" in body

    def test_health_returns_ok(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "timestamp" in body

    def test_openapi_schema_loads(self) -> None:
        """Ensures all routers registered without import errors."""
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Pricing API"
        assert "paths" in schema
