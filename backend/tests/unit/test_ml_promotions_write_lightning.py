"""
LIGHTNING (ofertas relámpago) enroll/remove (odd/tasks/promos-aplicar-lightning.md, S1-S3).

ML docs: enroll is `POST /seller-promotions/items/$ITEM_ID?app_version=v2` with
`{"deal_price", "stock", "promotion_type": "LIGHTNING"}`; remove is
`DELETE ...?app_version=v2&promotion_type=LIGHTNING`, and a started offer cannot be removed.

The live entry comes from `tests/fixtures/ml_promotions/lightning_candidate_docs_shape.json`
(docs shape, PENDING a real capture). All proxy/DB calls are mocked.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.usuario import Usuario
from app.services import ml_promotions_write_service as write_service
from app.services.ml_webhook_client import MLWebhookClient

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ml_promotions" / "lightning_candidate_docs_shape.json"
MLA = json.loads(FIXTURE.read_text())["mla"]
PROMO_ID = "LGH-MLA1000"
OK_201 = {"ok": True, "status_code": 201, "ambiguous": False, "body": {"price": 23818.35, "original_price": 27999}}


def _entry(**overrides: Any) -> Dict[str, Any]:
    entry = copy.deepcopy(json.loads(FIXTURE.read_text())["entry"])
    entry.update(overrides)
    return entry


def _live(*entries: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(entries) if entries else [_entry()]


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)
    monkeypatch.setattr(write_service, "_maybe_recompute_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_maybe_refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_clear_hay_mejores_after_enroll", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_record_write_log", lambda *a, **k: None)


def _enroll(live: Any, **kwargs: Any):
    with (
        patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=live) as mock_read,
        patch.object(write_service.ml_webhook_client, "enroll_item", return_value=OK_201) as mock_enroll,
    ):
        result = write_service.enroll_one_item(MLA, PROMO_ID, "LIGHTNING", **kwargs)
    return result, mock_read, mock_enroll


class TestLightningEnroll:
    def test_post_carries_price_and_stock_without_promotion_id(self) -> None:
        result, _, mock_enroll = _enroll(_live(), deal_price=23818.35, stock=5)

        assert result["status"] == "submitted"
        mock_enroll.assert_called_once()
        args, kwargs = mock_enroll.call_args
        assert args[0] == MLA
        assert args[1] is None  # the docs body has no promotion_id
        assert args[2] == "LIGHTNING"
        assert kwargs["deal_price"] == 23818.35
        assert kwargs["stock"] == 5

    def test_post_apply_price_check_against_201_price(self) -> None:
        result, _, _ = _enroll(_live(), deal_price=23818.35, stock=5)

        assert result["precio_confirmado"] == 23818.35
        assert result["precio_aplicado"] == 23818.35
        assert result["precio_difiere"] is False

    @pytest.mark.parametrize("price", [19599.29, 25199.11])
    def test_price_outside_live_range_sends_nothing(self, price: float) -> None:
        result, _, mock_enroll = _enroll(_live(), deal_price=price, stock=5)

        assert result["status"] == "rejected_out_of_range"
        mock_enroll.assert_not_called()

    @pytest.mark.parametrize("price", [19599.3, 25199.1])
    def test_range_bounds_are_inclusive(self, price: float) -> None:
        result, _, _ = _enroll(_live(), deal_price=price, stock=5)

        assert result["status"] == "submitted"

    @pytest.mark.parametrize("stock", [None, 0, 13])
    def test_stock_missing_or_outside_live_range_sends_nothing(self, stock: Any) -> None:
        result, _, mock_enroll = _enroll(_live(), deal_price=23818.35, stock=stock)

        assert result["status"] == "rejected_stock_out_of_range"
        assert result["submitted"] is False
        mock_enroll.assert_not_called()

    @pytest.mark.parametrize("stock", [1, 12])
    def test_stock_bounds_are_inclusive(self, stock: int) -> None:
        result, _, mock_enroll = _enroll(_live(), deal_price=23818.35, stock=stock)

        assert result["status"] == "submitted"
        assert mock_enroll.call_args.kwargs["stock"] == stock

    @pytest.mark.parametrize("stock_range", [None, {}, {"min": 1}, {"max": 12}])
    def test_missing_live_stock_range_fails_closed(self, stock_range: Any) -> None:
        result, _, mock_enroll = _enroll(_live(_entry(stock=stock_range)), deal_price=23818.35, stock=5)

        assert result["status"] == "rejected_stock_unresolved"
        mock_enroll.assert_not_called()

    @pytest.mark.parametrize("live_status", ["pending", "started", "finished", None])
    def test_not_candidate_fails_closed(self, live_status: Any) -> None:
        result, _, mock_enroll = _enroll(_live(_entry(status=live_status)), deal_price=23818.35, stock=5)

        assert result["status"] == "rejected_not_candidate"
        mock_enroll.assert_not_called()

    def test_missing_live_price_range_fails_closed(self) -> None:
        result, _, mock_enroll = _enroll(_live(_entry(min_discounted_price=None)), deal_price=23818.35, stock=5)

        assert result["status"] == "rejected_price_unresolved"
        mock_enroll.assert_not_called()

    def test_two_live_entries_with_the_same_id_fail_closed(self) -> None:
        live = _live(_entry(), _entry(start_date="2026-11-11T09:00:00Z"))
        result, _, mock_enroll = _enroll(live, deal_price=23818.35, stock=5)

        assert result["status"] == "rejected_promotion_ambiguous"
        mock_enroll.assert_not_called()

    def test_kill_switch_blocks_before_any_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", False)
        result, mock_read, mock_enroll = _enroll(_live(), deal_price=23818.35, stock=5)

        assert result["status"] == "disabled"
        mock_read.assert_not_called()
        mock_enroll.assert_not_called()

    def test_ambiguous_post_reconciles_instead_of_retrying(self) -> None:
        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=_live()),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": None, "ambiguous": True, "body": None},
            ) as mock_enroll,
            patch.object(
                write_service,
                "fetch_item_promotions",
                return_value=[{"promotion_id": PROMO_ID, "status": "pending", "promotion_type": "LIGHTNING"}],
            ),
        ):
            result = write_service.enroll_one_item(MLA, PROMO_ID, "LIGHTNING", deal_price=23818.35, stock=5)

        mock_enroll.assert_called_once()
        assert result["status"] == "reconciled_applied"

    def test_write_log_records_stock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: List[Dict[str, Any]] = []
        monkeypatch.setattr(write_service, "_record_write_log", lambda *a, **k: calls.append(k["sent"]))
        _enroll(_live(), deal_price=23818.35, stock=5)

        assert calls[0]["stock"] == 5
        assert calls[0]["deal_price"] == 23818.35


def _remove(live: Any):
    with (
        patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=live),
        patch.object(
            write_service.ml_webhook_client,
            "remove_item",
            return_value={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        ) as mock_remove,
    ):
        result = write_service.remove_one_item(MLA, "LIGHTNING", PROMO_ID)
    return result, mock_remove


class TestLightningRemove:
    def test_pending_is_removed_without_promotion_id(self) -> None:
        result, mock_remove = _remove(_live(_entry(status="pending")))

        assert result["status"] == "submitted"
        mock_remove.assert_called_once_with(MLA, "LIGHTNING", None)

    def test_started_is_refused(self) -> None:
        result, mock_remove = _remove(_live(_entry(status="started")))

        assert result["status"] == "rejected_started_not_removable"
        assert "pausá la publicación" in result["detail"]
        mock_remove.assert_not_called()

    @pytest.mark.parametrize("live_status", ["candidate", "finished", None])
    def test_not_enrolled_is_refused(self, live_status: Any) -> None:
        result, mock_remove = _remove(_live(_entry(status=live_status)))

        assert result["status"] == "rejected_not_removable"
        mock_remove.assert_not_called()

    def test_live_read_unavailable_is_refused(self) -> None:
        result, mock_remove = _remove(None)

        assert result["status"] == "rejected_read_unavailable"
        mock_remove.assert_not_called()


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestLightningClientBody:
    def test_enroll_body_is_the_documented_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: Dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json={"price": 23818.35, "original_price": 27999})

        _patch_httpx(monkeypatch, handler)
        asyncio.run(MLWebhookClient().enroll_item(MLA, None, "LIGHTNING", 23818.35, stock=5))

        assert seen["body"] == {"promotion_type": "LIGHTNING", "deal_price": 23818.35, "stock": 5}

    def test_remove_params_are_the_documented_ones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: Dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200)

        _patch_httpx(monkeypatch, handler)
        asyncio.run(MLWebhookClient().remove_item(MLA, "LIGHTNING", None))

        assert seen["params"] == {"promotion_type": "LIGHTNING"}


class _AllowAll:
    def tiene_permiso(self, usuario: Usuario, codigo: str) -> bool:
        return True


@pytest.fixture()
def api() -> TestClient:
    user = Usuario()
    user.id = 7
    user.username = "tester"
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: None
    try:
        with patch("app.routers.ml_promotions.PermisosService", return_value=_AllowAll()):
            yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


class TestLightningEndpoints:
    def test_enroll_passes_stock_to_the_service(self, api: TestClient) -> None:
        with patch(
            "app.routers.ml_promotions.enroll_one_item",
            return_value={"submitted": True, "status": "submitted", "price": 23818.35, "status_code": 201},
        ) as mock_enroll:
            response = api.post(
                f"/api/promociones/item/{MLA}",
                json={"promotion_id": PROMO_ID, "promotion_type": "LIGHTNING", "deal_price": 23818.35, "stock": 5},
            )

        assert response.status_code == 200
        assert mock_enroll.call_args.kwargs["stock"] == 5

    @pytest.mark.parametrize(
        "status_name", ["rejected_stock_out_of_range", "rejected_stock_unresolved", "rejected_promotion_ambiguous"]
    )
    def test_enroll_rejections_are_422(self, api: TestClient, status_name: str) -> None:
        with patch(
            "app.routers.ml_promotions.enroll_one_item",
            return_value={"submitted": False, "status": status_name, "detail": "x"},
        ):
            response = api.post(
                f"/api/promociones/item/{MLA}",
                json={"promotion_id": PROMO_ID, "promotion_type": "LIGHTNING", "deal_price": 1.0, "stock": 5},
            )

        assert response.status_code == 422

    @pytest.mark.parametrize("status_name", ["rejected_started_not_removable", "rejected_not_removable"])
    def test_remove_refusals_are_409(self, api: TestClient, status_name: str) -> None:
        with patch(
            "app.routers.ml_promotions.remove_one_item",
            return_value={"submitted": False, "status": status_name, "detail": "msg"},
        ):
            response = api.delete(
                f"/api/promociones/item/{MLA}", params={"promotion_type": "LIGHTNING", "promotion_id": PROMO_ID}
            )

        assert response.status_code == 409
        assert response.json()["error"]["message"] == "msg"
