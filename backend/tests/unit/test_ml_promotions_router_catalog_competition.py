"""
Unit tests for the catalog-competition endpoints on the ml_promotions
router (promos-catalog-prices-and-official-store, slice C2).

  GET  /api/promociones/catalogo-competencia/{mla_id}            -> CatalogCompetitionSnapshot
  POST /api/promociones/catalogo-competencia/{mla_id}/refresh    -> CatalogCompetitionSnapshot

Spec coverage:
  C2.1 — refresh is scoped to exactly one MLA, calls the shared writer
         with a single-element list.
  C2.3 — fetch_status='not_catalog' -> panel-visible "no aplica" state,
         not hidden, not an error.
  C2.4/C2.5 — never-fetched -> 200 with fetch_status='never', NEVER 404,
         and the read endpoint makes no fetch (no auto-fetch on open).
  C2.6 — only same-bucket AND strictly-cheaper competitors are returned
         in `undercutting`.
  Permissions: promos.ver gates the read, promos.escribir gates the
  refresh — same split as the sibling promo endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.models.usuario import Usuario


def _fake_user() -> Usuario:
    user = Usuario()
    user.id = 1
    user.username = "tester"
    return user


class _FakePermisosService:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[str] = []

    def tiene_permiso(self, usuario, codigo: str) -> bool:
        self.calls.append(codigo)
        return self.allowed


def _unauthenticated() -> Usuario:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


@pytest.fixture()
def client(db) -> TestClient:
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _fake_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestReadEndpoint:
    def test_never_fetched_returns_200_never_not_404(self, client: TestClient, db) -> None:
        fake_service = _FakePermisosService(allowed=True)
        with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
            response = client.get("/api/promociones/catalogo-competencia/MLA999999")

        assert response.status_code == 200
        body = response.json()
        assert body["fetch_status"] == "never"
        assert body["undercutting"] == []
        assert "promos.ver" in fake_service.calls

    def test_ok_snapshot_returns_only_cheaper_same_bucket_competitors(self, client: TestClient, db) -> None:
        row = MLCatalogCompetition(
            mla="MLA111",
            fecha_consulta=datetime.now(UTC),
            fetch_status="ok",
            our_item_id="MLA111",
            our_price=1000.0,
            our_currency_id="ARS",
            our_bucket_key="gold_special|0",
            competitors=[
                {
                    "item_id": "CHEAPER",
                    "price": 900.0,
                    "currency_id": "ARS",
                    "price_ars": 900.0,
                    "same_bucket": True,
                    "is_cheaper_than_us": True,
                    "markup": 30.0,
                },
                {
                    "item_id": "PRICIER",
                    "price": 1100.0,
                    "currency_id": "ARS",
                    "price_ars": 1100.0,
                    "same_bucket": True,
                    "is_cheaper_than_us": False,
                    "markup": None,
                },
                {
                    "item_id": "OTHER_BUCKET",
                    "price": 500.0,
                    "currency_id": "ARS",
                    "price_ars": 500.0,
                    "same_bucket": False,
                    "is_cheaper_than_us": True,
                    "markup": None,
                },
            ],
            competitor_count=3,
        )
        db.add(row)
        db.commit()

        fake_service = _FakePermisosService(allowed=True)
        with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
            response = client.get("/api/promociones/catalogo-competencia/MLA111")

        assert response.status_code == 200
        body = response.json()
        assert body["fetch_status"] == "ok"
        assert body["competitor_count"] == 3
        assert [c["item_id"] for c in body["undercutting"]] == ["CHEAPER"]

    def test_not_catalog_returns_visible_state_not_hidden(self, client: TestClient, db) -> None:
        row = MLCatalogCompetition(
            mla="MLA222",
            fecha_consulta=datetime.now(UTC),
            fetch_status="not_catalog",
            competitors=[],
            competitor_count=0,
        )
        db.add(row)
        db.commit()

        fake_service = _FakePermisosService(allowed=True)
        with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
            response = client.get("/api/promociones/catalogo-competencia/MLA222")

        assert response.status_code == 200
        assert response.json()["fetch_status"] == "not_catalog"

    def test_error_row_returns_error_state_with_detail(self, client: TestClient, db) -> None:
        row = MLCatalogCompetition(
            mla="MLA333",
            fecha_consulta=datetime.now(UTC),
            fetch_status="error",
            competitors=[],
            competitor_count=0,
            error_detail="HTTP 500",
        )
        db.add(row)
        db.commit()

        fake_service = _FakePermisosService(allowed=True)
        with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
            response = client.get("/api/promociones/catalogo-competencia/MLA333")

        assert response.status_code == 200
        body = response.json()
        assert body["fetch_status"] == "error"
        assert body["error_detail"] == "HTTP 500"

    def test_missing_permission_returns_403(self, client: TestClient, db) -> None:
        fake_service = _FakePermisosService(allowed=False)
        with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
            response = client.get("/api/promociones/catalogo-competencia/MLA999999")

        assert response.status_code == 403
        assert "promos.ver" in fake_service.calls

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        app.dependency_overrides[get_current_user] = _unauthenticated
        response = client.get("/api/promociones/catalogo-competencia/MLA999999")
        assert response.status_code == 401


class TestRefreshEndpoint:
    def test_refresh_calls_shared_writer_with_single_mla(self, client: TestClient, db) -> None:
        fake_service = _FakePermisosService(allowed=True)
        fresh_row = MLCatalogCompetition(
            mla="MLA444",
            fecha_consulta=datetime.now(UTC),
            fetch_status="ok",
            our_item_id="MLA444",
            our_price=1000.0,
            competitors=[],
            competitor_count=0,
        )
        writer = AsyncMock(return_value=[fresh_row])
        with (
            patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
            patch("app.routers.ml_promotions.refrescar_competencia_catalogo", writer),
        ):
            response = client.post("/api/promociones/catalogo-competencia/MLA444/refresh")

        assert response.status_code == 200
        assert response.json()["fetch_status"] == "ok"
        writer.assert_awaited_once()
        called_db, called_mlas = writer.await_args.args
        assert called_mlas == ["MLA444"]
        assert "promos.escribir" in fake_service.calls

    def test_missing_permission_returns_403_no_writer_call(self, client: TestClient, db) -> None:
        fake_service = _FakePermisosService(allowed=False)
        writer = AsyncMock()
        with (
            patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
            patch("app.routers.ml_promotions.refrescar_competencia_catalogo", writer),
        ):
            response = client.post("/api/promociones/catalogo-competencia/MLA444/refresh")

        assert response.status_code == 403
        writer.assert_not_awaited()

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        app.dependency_overrides[get_current_user] = _unauthenticated
        response = client.post("/api/promociones/catalogo-competencia/MLA444/refresh")
        assert response.status_code == 401
