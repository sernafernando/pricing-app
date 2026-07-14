"""
Unit tests for the ml_promotions router (READ-ONLY, PR1).

Endpoints under test (prefix /api/promociones):
  GET /api/promociones                       -> list promotions (table)
  GET /api/promociones/{promotion_id}/items   -> items of a promotion (table)
  GET /api/promociones/item/{mla_id}          -> promotions of a single MLA (table)

Write endpoints (enroll/remove) are PR2 and are NOT covered here.

Spec coverage:
  REQ-1 — ML_WEBHOOK_DB_URL unset -> 503 on every read endpoint, before any
          service call touches the DB
  REQ-2 — missing promos.ver permission -> 403, no downstream call
  REQ-3 — GET list (table) happy path
  REQ-4 — GET promo items missing promotion_type -> 422
  REQ-5 — GET promo items happy path (promotion_type required, present)
  REQ-6 — GET per-item promotions happy path, status mapping passthrough
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
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


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _override_auth(allowed_permiso: bool = True):
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = lambda: iter([None]).__next__() or object()

    fake_service = _FakePermisosService(allowed_permiso)
    return fake_service


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestPermissionGate:
    def test_missing_permission_returns_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=False)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 403
        assert "promos.ver" in fake_service.calls


class TestDbUnavailable:
    def test_list_promotions_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotions",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_promotion_items_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotion_items",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones/DEAL-1/items", params={"promotion_type": "DEAL"})
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_item_promotions_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 503


class TestListPromotions:
    def test_happy_path(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotions",
                    return_value=[
                        {
                            "promotion_id": "SELLER_CAMPAIGN",
                            "promotion_type": "SELLER_CAMPAIGN",
                            "sub_type": None,
                            "status": "started",
                            "name": "Campaña Vendedor",
                            "start_date": None,
                            "finish_date": None,
                            "deadline_date": None,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ),
            ):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["promotions"][0]["promotion_id"] == "SELLER_CAMPAIGN"


class TestPromotionItems:
    def test_missing_promotion_type_returns_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.get("/api/promociones/DEAL-1/items")
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_happy_path(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotion_items",
                    return_value=[
                        {
                            "mla": "MLA111",
                            "promotion_id": "DEAL-1",
                            "promotion_type": "DEAL",
                            "sub_type": None,
                            "status": "candidate",
                            "original_price": 1000.0,
                            "price": 900.0,
                            "min_discounted_price": 850.0,
                            "max_discounted_price": 950.0,
                            "suggested_discounted_price": 900.0,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ),
            ):
                response = client.get("/api/promociones/DEAL-1/items", params={"promotion_type": "DEAL"})
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["mla"] == "MLA111"


def _passthrough_enriquecer(db, mla, promociones):
    """Test double for `enriquecer_markup_por_promo`: sets a fixed
    `nuestro_markup` per promo without touching the (fake/dummy) db."""
    for promo in promociones:
        promo["nuestro_markup"] = 18.5
    return promociones


class TestItemPromotions:
    def test_happy_path_status_mapping(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    return_value=[
                        {
                            "mla": "MLA123456789",
                            "promotion_id": "DEAL-1",
                            "promotion_type": "DEAL",
                            "sub_type": None,
                            "status": "started",
                            "original_price": 1000.0,
                            "price": 900.0,
                            "min_discounted_price": 850.0,
                            "max_discounted_price": 950.0,
                            "suggested_discounted_price": 900.0,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ) as mock_fetch,
                patch(
                    "app.routers.ml_promotions.enriquecer_markup_por_promo",
                    side_effect=_passthrough_enriquecer,
                ),
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["promotions"][0]["status"] == "started"
        # The endpoint must request only candidate|started promotions: the
        # backfilled ml_item_promotions table is upsert-only with no stale
        # cleanup, so finished promos would otherwise linger in the display.
        mock_fetch.assert_called_once_with("MLA123456789", active_only=True)

    def test_nuestro_markup_present_per_promo(self, client: TestClient) -> None:
        """R6/R7 — `nuestro_markup` is present per promo entry (number or
        null), independently computed per promo."""
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    return_value=[
                        {
                            "mla": "MLA123456789",
                            "promotion_id": "SMART-1",
                            "promotion_type": "SMART",
                            "sub_type": None,
                            "status": "started",
                            "original_price": 1000.0,
                            "price": 900.0,
                            "min_discounted_price": 850.0,
                            "max_discounted_price": 950.0,
                            "suggested_discounted_price": 900.0,
                            "payload": {"meli_percentage": 1.4},
                            "updated_at": None,
                        },
                        {
                            "mla": "MLA123456789",
                            "promotion_id": "DEAL-1",
                            "promotion_type": "DEAL",
                            "sub_type": None,
                            "status": "candidate",
                            "original_price": 1000.0,
                            "price": 0.0,
                            "min_discounted_price": None,
                            "max_discounted_price": None,
                            "suggested_discounted_price": None,
                            "payload": {},
                            "updated_at": None,
                        },
                    ],
                ),
                patch(
                    "app.routers.ml_promotions.enriquecer_markup_por_promo",
                    side_effect=lambda db, mla, promos: (
                        [{**promos[0], "nuestro_markup": 22.3}, {**promos[1], "nuestro_markup": None}]
                    ),
                ),
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["promotions"][0]["nuestro_markup"] == 22.3
        assert body["promotions"][1]["nuestro_markup"] is None

    def test_db_unavailable_still_503_before_enrichment(self, client: TestClient) -> None:
        """R5.3 — ML_WEBHOOK_DB_URL unset behavior is unchanged: 503 happens
        before enrichment is ever attempted."""
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo") as mock_enrich,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 503
        mock_enrich.assert_not_called()


def _item_promo(promotion_id: str, status: str, promotion_type: str = "SELLER_CAMPAIGN") -> dict:
    return {
        "mla": "MLA123456789",
        "promotion_id": promotion_id,
        "promotion_type": promotion_type,
        "sub_type": None,
        "status": status,
        "original_price": 1000.0,
        "price": 900.0,
        "min_discounted_price": 850.0,
        "max_discounted_price": 950.0,
        "suggested_discounted_price": 900.0,
        "payload": {},
        "updated_at": None,
    }


class TestReconcileMultiStarted:
    """ml_item_promotions is upsert-only with no stale cleanup: a promo
    bumped out of `started` can linger as `started`. More than one
    `started` row for the same MLA is impossible in reality (ML only
    ever has one truly applied promo) -> a stale-signal trigger for
    reconciling against the live proxy read.
    """

    def test_multi_started_reconciled_against_live(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("A-1", "started"),
            _item_promo("B-1", "started"),
        ]
        live_payload = [
            {"id": "A-1", "type": "SELLER_CAMPAIGN", "status": "candidate"},
            {"id": "B-1", "type": "SELLER_CAMPAIGN", "status": "started"},
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                    return_value=live_payload,
                ) as mock_live,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        mock_live.assert_called_once_with("MLA123456789")
        body = response.json()
        statuses = [p["status"] for p in body["promotions"]]
        assert statuses.count("started") == 1
        by_id = {p["promotion_id"]: p["status"] for p in body["promotions"]}
        assert by_id["A-1"] == "candidate"
        assert by_id["B-1"] == "started"

    def test_single_started_no_live_call(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("A-1", "started"),
            _item_promo("B-1", "candidate"),
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                ) as mock_live,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        mock_live.assert_not_called()
        body = response.json()
        assert body["promotions"][0]["status"] == "started"
        assert body["promotions"][1]["status"] == "candidate"

    def test_zero_started_no_live_call(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("A-1", "candidate"),
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                ) as mock_live,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        mock_live.assert_not_called()
        assert response.json()["promotions"][0]["status"] == "candidate"

    def test_multi_started_live_read_fails_graceful_fallback(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("A-1", "started"),
            _item_promo("B-1", "started"),
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                    side_effect=RuntimeError("proxy unreachable"),
                ) as mock_live,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        mock_live.assert_called_once()
        body = response.json()
        statuses = [p["status"] for p in body["promotions"]]
        assert statuses.count("started") == 2

    def test_multi_started_live_read_returns_none_graceful_fallback(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("A-1", "started"),
            _item_promo("B-1", "started"),
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                    return_value=None,
                ) as mock_live,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        mock_live.assert_called_once()
        body = response.json()
        statuses = [p["status"] for p in body["promotions"]]
        assert statuses.count("started") == 2

    def test_live_entry_keyed_by_id_matched_against_promotion_id(self, client: TestClient) -> None:
        """Guards against the bare-list/`id` contract: live entries are
        keyed by `id` (not `promotion_id`), matched against the table
        row's `promotion_id`."""
        fake_service = _override_auth(allowed_permiso=True)
        table_rows = [
            _item_promo("C-MLA1332399", "started", promotion_type="SELLER_CAMPAIGN"),
            _item_promo("C-MLA1334584", "started", promotion_type="SELLER_CAMPAIGN"),
        ]
        live_payload = [
            {"id": "C-MLA1332399", "type": "SELLER_CAMPAIGN", "status": "candidate"},
            {"id": "C-MLA1334584", "type": "SELLER_CAMPAIGN", "status": "started"},
        ]
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=table_rows),
                patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=_passthrough_enriquecer),
                patch(
                    "app.services.ml_promotions_service.ml_webhook_client.get_item_promotions",
                    return_value=live_payload,
                ),
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        by_id = {p["promotion_id"]: p["status"] for p in body["promotions"]}
        assert by_id["C-MLA1332399"] == "candidate"
        assert by_id["C-MLA1334584"] == "started"
