"""
Incident 2026-10-05 (MLA2385168136, SMART P-MLA18091086): the panel showed a
stale ~$469k offer, the operator applied it, and ML enrolled the item at its
CURRENT offer, $372.408,72, with negative markup. ML sets the price of
SMART / PRE_NEGOTIATED / PRICE_MATCHING offers and recalculates candidates
daily; the enroll POST carries only the offer_id, so whatever ML holds at
that moment is what gets applied.

These tests pin the guard: the request carries the price the operator SAW,
the backend re-reads the live offer right before the POST, and anything
other than "same candidate, same price to the cent" sends NOTHING to ML.
After a submitted enroll, the price ML says it applied is compared with the
confirmed one and a difference is flagged.

All proxy calls go through a fake `ml_webhook_client` — no network, no DB.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.usuario import Usuario
from app.services import ml_promotions_pricing as pricing
from app.services import ml_promotions_write_service as write_service

MLA = "MLA2385168136"
PROMO_ID = "P-MLA18091086"
LIVE_PRICE = 372408.72
STALE_PRICE = 469120.0


def _live_entry(
    price: Optional[float] = LIVE_PRICE,
    status: Optional[str] = "candidate",
    promotion_type: str = "SMART",
    ref_id: Optional[str] = "CANDIDATE-MLA2385168136-71644242247",
) -> Dict[str, Any]:
    """Shape captured from the live proxy on 2026-10-05 for this MLA."""
    return {
        "id": PROMO_ID,
        "type": promotion_type,
        "status": status,
        "price": price,
        "original_price": 699805,
        "meli_percentage": 3.243,
        "seller_percentage": 43.757,
        "ref_id": ref_id,
    }


class FakeProxy:
    """Records every call; `live` is what GET /promociones/item returns
    (None = the read failed), `enroll_result` what the POST returns."""

    def __init__(
        self,
        live: Optional[List[Dict[str, Any]]],
        enroll_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.live = live
        self.enroll_result = enroll_result or {
            "ok": True,
            "status_code": 201,
            "ambiguous": False,
            "body": {"offer_id": "OFFER-MLA2385168136-1", "price": LIVE_PRICE, "original_price": 699805},
        }
        self.reads = 0
        self.enrolls: List[Dict[str, Any]] = []

    def get_item_promotions(self, mla_id: str) -> Optional[List[Dict[str, Any]]]:
        self.reads += 1
        return self.live

    def enroll_item(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.enrolls.append({"args": args, "kwargs": kwargs})
        return self.enroll_result


@pytest.fixture(autouse=True)
def _no_post_write_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service, "_maybe_recompute_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_maybe_refresh_after_write", lambda *a, **k: None)


@pytest.fixture()
def writes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)


def _install(proxy: FakeProxy):
    return (
        patch.object(write_service.ml_webhook_client, "get_item_promotions", side_effect=proxy.get_item_promotions),
        patch.object(write_service.ml_webhook_client, "enroll_item", side_effect=proxy.enroll_item),
    )


def _enroll(proxy: FakeProxy, promotion_type: str = "SMART", **kwargs: Any) -> Dict[str, Any]:
    read_patch, enroll_patch = _install(proxy)
    with read_patch, enroll_patch:
        return write_service.enroll_one_item(MLA, PROMO_ID, promotion_type, **kwargs)


# ── Service: pre-apply guard ─────────────────────────────────────


@pytest.mark.usefixtures("writes_on")
class TestPreApplyGuard:
    @pytest.mark.parametrize("promotion_type", ["SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"])
    def test_unchanged_price_enrolls(self, promotion_type: str) -> None:
        proxy = FakeProxy([_live_entry(promotion_type=promotion_type)])

        result = _enroll(proxy, promotion_type, precio_visto=LIVE_PRICE)

        assert result["status"] == "submitted"
        assert len(proxy.enrolls) == 1

    def test_changed_price_rejects_and_sends_nothing(self) -> None:
        proxy = FakeProxy([_live_entry(price=LIVE_PRICE)])

        result = _enroll(proxy, precio_visto=STALE_PRICE, markup_visto=12.5)

        assert proxy.enrolls == []
        assert result["submitted"] is False
        assert result["status"] == "rejected_price_changed"
        assert result["precio_visto"] == STALE_PRICE
        assert result["precio_actual"] == LIVE_PRICE
        # The live entry travels back so the router can price it with the
        # SAME markup chain the panel uses.
        assert result["live_promo"]["meli_percentage"] == 3.243

    def test_one_cent_difference_is_a_change(self) -> None:
        proxy = FakeProxy([_live_entry(price=LIVE_PRICE)])

        result = _enroll(proxy, precio_visto=LIVE_PRICE - 0.01)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_price_changed"

    def test_float_noise_below_a_cent_is_not_a_change(self) -> None:
        # 0.1 + 0.2 style noise from JSON floats must not block an apply.
        proxy = FakeProxy([_live_entry(price=372408.72)])

        result = _enroll(proxy, precio_visto=372408.72000000003)

        assert result["status"] == "submitted"

    @pytest.mark.parametrize("seen", [None, 0, -1])
    def test_missing_seen_price_is_refused_before_any_proxy_call(self, seen: Optional[float]) -> None:
        proxy = FakeProxy([_live_entry()])

        result = _enroll(proxy, precio_visto=seen)

        assert proxy.reads == 0
        assert proxy.enrolls == []
        assert result["status"] == "rejected_price_unconfirmed"

    def test_live_read_failure_blocks(self) -> None:
        proxy = FakeProxy(None)

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_read_unavailable"

    @pytest.mark.parametrize("status", ["started", "pending", "finished", None])
    def test_offer_no_longer_candidate_blocks(self, status: Optional[str]) -> None:
        proxy = FakeProxy([_live_entry(status=status)])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_not_candidate"

    def test_offer_gone_from_live_blocks(self) -> None:
        proxy = FakeProxy([])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_promotion_not_found"

    def test_kill_switch_off_blocks_as_today(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", False)
        proxy = FakeProxy([_live_entry()])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert proxy.reads == 0
        assert proxy.enrolls == []
        assert result["status"] == "disabled"

    def test_seller_priced_types_are_not_guarded(self) -> None:
        """DEAL/SELLER_CAMPAIGN: the operator types deal_price and that exact
        price is sent; ML cannot move it under them. No precio_visto needed."""
        proxy = FakeProxy(
            [
                {
                    "id": PROMO_ID,
                    "type": "DEAL",
                    "status": "candidate",
                    "min_discounted_price": 100.0,
                    "max_discounted_price": 200.0,
                    "suggested_discounted_price": 150.0,
                }
            ]
        )

        result = _enroll(proxy, "DEAL", deal_price=150.0)

        assert result["status"] == "submitted"


# ── Service: post-apply check ────────────────────────────────────


@pytest.mark.usefixtures("writes_on")
class TestPostApplyCheck:
    def test_same_returned_price_is_not_flagged(self) -> None:
        proxy = FakeProxy([_live_entry()])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert result["precio_confirmado"] == LIVE_PRICE
        assert result["precio_aplicado"] == LIVE_PRICE
        assert result["precio_difiere"] is False

    def test_different_returned_price_is_flagged_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        proxy = FakeProxy(
            [_live_entry()],
            enroll_result={
                "ok": True,
                "status_code": 201,
                "ambiguous": False,
                "body": {"offer_id": "OFFER-X", "price": 350000.0, "original_price": 699805},
            },
        )

        with caplog.at_level("ERROR", logger=write_service.logger.name):
            result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert result["status"] == "submitted"
        assert result["precio_aplicado"] == 350000.0
        assert result["precio_confirmado"] == LIVE_PRICE
        assert result["precio_difiere"] is True
        assert any("precio aplicado difiere" in r.getMessage() for r in caplog.records)

    def test_missing_returned_price_is_unverified_not_ok(self) -> None:
        """No price in ML's 201 means we could not verify: None, never False."""
        proxy = FakeProxy(
            [_live_entry()],
            enroll_result={"ok": True, "status_code": 201, "ambiguous": False, "body": {"offer_id": "OFFER-X"}},
        )

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert result["status"] == "submitted"
        assert result["precio_aplicado"] is None
        assert result["precio_difiere"] is None


# ── Markup of a live offer: same chain the panel uses ───────────


class TestMarkupDeOfertaLive:
    def test_feeds_the_live_entry_as_payload_so_co_funding_counts(self) -> None:
        captured: Dict[str, Any] = {}

        def _fake_enriquecer(db: Any, mla: str, promos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            captured.update(promos[0])
            promos[0]["nuestro_markup"] = -4.2
            return promos

        with patch.object(pricing, "enriquecer_markup_por_promo", side_effect=_fake_enriquecer):
            markup = pricing.markup_de_oferta_live(object(), MLA, "SMART", _live_entry())

        assert markup == -4.2
        assert captured["promotion_type"] == "SMART"
        assert captured["price"] == LIVE_PRICE
        assert captured["original_price"] == 699805
        assert captured["payload"]["meli_percentage"] == 3.243

    def test_price_override_prices_what_ml_applied(self) -> None:
        captured: Dict[str, Any] = {}

        def _fake_enriquecer(db: Any, mla: str, promos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            captured.update(promos[0])
            promos[0]["nuestro_markup"] = 1.0
            return promos

        with patch.object(pricing, "enriquecer_markup_por_promo", side_effect=_fake_enriquecer):
            pricing.markup_de_oferta_live(object(), MLA, "SMART", _live_entry(), price=350000.0)

        assert captured["price"] == 350000.0

    def test_never_raises(self) -> None:
        with patch.object(pricing, "enriquecer_markup_por_promo", side_effect=RuntimeError("db down")):
            assert pricing.markup_de_oferta_live(object(), MLA, "SMART", _live_entry()) is None


# ── Router: HTTP contract ────────────────────────────────────────


class _AllowAll:
    def tiene_permiso(self, usuario: Any, codigo: str) -> bool:
        return True


def _fake_user() -> Usuario:
    user = Usuario()
    user.id = 1
    user.username = "tester"
    return user


@pytest.fixture()
def client() -> Any:
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = lambda: object()
    with patch("app.routers.ml_promotions.PermisosService", return_value=_AllowAll()):
        yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _post(client: TestClient, proxy: FakeProxy, body: Dict[str, Any], markup: Optional[float] = -7.5):
    read_patch, enroll_patch = _install(proxy)
    with (
        read_patch,
        enroll_patch,
        patch("app.routers.ml_promotions.markup_de_oferta_live", return_value=markup) as mock_markup,
    ):
        response = client.post(f"/api/promociones/item/{MLA}", json=body)
    return response, mock_markup


@pytest.mark.usefixtures("writes_on")
class TestEnrollRouterGuard:
    def test_price_changed_is_409_with_new_price_and_markup(self, client: TestClient) -> None:
        proxy = FakeProxy([_live_entry()])

        response, mock_markup = _post(
            client,
            proxy,
            {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": STALE_PRICE, "markup_visto": 12.5},
        )

        assert response.status_code == 409
        # The app-wide HTTPException handler returns a dict detail AS the body
        # root (app/core/exceptions.py), so the panel reads it at data.*.
        detail = response.json()
        assert detail["status"] == "rejected_price_changed"
        assert detail["precio_visto"] == STALE_PRICE
        assert detail["precio_actual"] == LIVE_PRICE
        assert detail["markup_actual"] == -7.5
        assert "mensaje" in detail
        assert proxy.enrolls == []
        # Priced from the LIVE entry, not the stale mirror.
        args = mock_markup.call_args.args
        assert args[1] == MLA and args[2] == "SMART" and args[3]["price"] == LIVE_PRICE

    def test_unchanged_price_is_200_submitted(self, client: TestClient) -> None:
        proxy = FakeProxy([_live_entry()])

        response, _ = _post(
            client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": LIVE_PRICE}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "submitted"
        assert body["precio_difiere"] is False
        assert "live_promo" not in body
        assert len(proxy.enrolls) == 1

    def test_missing_seen_price_is_422(self, client: TestClient) -> None:
        proxy = FakeProxy([_live_entry()])

        response, _ = _post(client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART"})

        assert response.status_code == 422
        assert proxy.enrolls == []

    def test_not_candidate_is_409_with_a_message(self, client: TestClient) -> None:
        proxy = FakeProxy([_live_entry(status="started")])

        response, _ = _post(
            client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": LIVE_PRICE}
        )

        assert response.status_code == 409
        assert "ya no está disponible" in response.json()["error"]["message"]
        assert proxy.enrolls == []

    def test_live_read_failure_is_503(self, client: TestClient) -> None:
        proxy = FakeProxy(None)

        response, _ = _post(
            client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": LIVE_PRICE}
        )

        assert response.status_code == 503
        assert proxy.enrolls == []

    def test_returned_price_differs_is_flagged_with_its_markup(self, client: TestClient) -> None:
        proxy = FakeProxy(
            [_live_entry()],
            enroll_result={
                "ok": True,
                "status_code": 201,
                "ambiguous": False,
                "body": {"offer_id": "OFFER-X", "price": 350000.0, "original_price": 699805},
            },
        )

        response, mock_markup = _post(
            client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": LIVE_PRICE}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["precio_difiere"] is True
        assert body["precio_aplicado"] == 350000.0
        assert body["precio_confirmado"] == LIVE_PRICE
        assert body["markup_aplicado"] == -7.5
        assert mock_markup.call_args.kwargs["price"] == 350000.0

    def test_kill_switch_off_is_403_and_nothing_read(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", False)
        proxy = FakeProxy([_live_entry()])

        response, _ = _post(
            client, proxy, {"promotion_id": PROMO_ID, "promotion_type": "SMART", "precio_visto": LIVE_PRICE}
        )

        assert response.status_code == 403
        assert proxy.reads == 0
        assert proxy.enrolls == []


# ── Freshness (T4) ───────────────────────────────────────────────


class _OnlyRead:
    """A `promos.ver`-only user."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def tiene_permiso(self, usuario: Any, codigo: str) -> bool:
        self.calls.append(codigo)
        return codigo == "promos.ver"


@pytest.fixture()
def read_only_client() -> Any:
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = lambda: object()
    with patch("app.routers.ml_promotions.PermisosService", return_value=_OnlyRead()):
        yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestRefreshIsARead:
    def test_read_only_user_can_reconcile_the_mirror(self, read_only_client: TestClient) -> None:
        """The refresh only reconciles our mirror from ML (no write to ML),
        so a `promos.ver` user opening the panel must get fresh data too."""
        from app.services.ml_webhook_client import RefreshOutcome

        with patch(
            "app.routers.ml_promotions.ml_webhook_client.refresh_item_promotions",
            return_value=RefreshOutcome(ok=True),
        ):
            response = read_only_client.post(f"/api/promociones/item/{MLA}/refresh")

        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestMirrorReadNeverWaitsOnML:
    """GET /promociones/item/{mla} reads only the mirror. An empty mirror is
    common (items with no promos), so a live confirmation there would put a
    proxy round-trip (and its failures) on every panel open."""

    def test_empty_mirror_does_not_call_the_live_proxy(self, read_only_client: TestClient) -> None:
        with (
            patch("app.routers.ml_promotions.fetch_item_promotions", return_value=[]),
            patch("app.routers.ml_promotions.enriquecer_markup_por_promo", side_effect=lambda db, mla, p: p),
            patch.object(write_service.ml_webhook_client, "get_item_promotions") as mock_live,
        ):
            response = read_only_client.get(f"/api/promociones/item/{MLA}")

        assert response.status_code == 200
        assert response.json()["count"] == 0
        mock_live.assert_not_called()


class TestConfirmacionML:
    """GET /promociones/item/{mla}/confirmacion-ml: the panel asks it AFTER
    rendering an empty mirror. Incident: the mirror had NO rows for
    MLA2385168136 while the live proxy returned 9 promos. It must never
    raise and never wait long."""

    URL = f"/api/promociones/item/{MLA}/confirmacion-ml"

    def _get(self, client: TestClient, **live_kwargs: Any):
        with patch.object(write_service.ml_webhook_client, "get_item_promotions", **live_kwargs) as mock_live:
            response = client.get(self.URL)
        return response, mock_live

    def test_ml_has_active_promos_is_not_confirmed(self, read_only_client: TestClient) -> None:
        response, _ = self._get(
            read_only_client,
            return_value=[_live_entry(), _live_entry(status="started"), _live_entry(status="finished")],
        )

        assert response.status_code == 200
        assert response.json()["sin_promos_confirmado"] is False
        assert response.json()["promos_en_ml"] == 2

    def test_ml_agrees_there_are_none(self, read_only_client: TestClient) -> None:
        response, _ = self._get(read_only_client, return_value=[_live_entry(status="finished")])

        assert response.json()["sin_promos_confirmado"] is True
        assert response.json()["promos_en_ml"] == 0

    def test_live_read_failure_is_unconfirmed(self, read_only_client: TestClient) -> None:
        response, _ = self._get(read_only_client, return_value=None)

        assert response.status_code == 200
        assert response.json()["sin_promos_confirmado"] is False
        assert response.json()["promos_en_ml"] is None

    @pytest.mark.parametrize("exc", [ValueError("boom"), KeyError("x"), RuntimeError("no db"), TimeoutError()])
    def test_any_exception_is_200_unconfirmed(self, read_only_client: TestClient, exc: Exception) -> None:
        response, _ = self._get(read_only_client, side_effect=exc)

        assert response.status_code == 200
        assert response.json()["sin_promos_confirmado"] is False

    def test_garbage_payload_is_unconfirmed(self, read_only_client: TestClient) -> None:
        response, _ = self._get(read_only_client, return_value={"unexpected": "shape"})

        assert response.status_code == 200
        assert response.json()["sin_promos_confirmado"] is False

    def test_log_says_what_happened_not_what_the_caller_saw(
        self, read_only_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The endpoint cannot know the mirror state, so its logs must not
        assert one; they say what the live read returned."""
        from app.routers import ml_promotions

        with caplog.at_level("WARNING", logger=ml_promotions.logger.name):
            self._get(read_only_client, return_value=None)
            failed = [r.getMessage() for r in caplog.records]
            caplog.clear()
            self._get(read_only_client, return_value=[_live_entry()])
            reported = [r.getMessage() for r in caplog.records]

        assert len(failed) == 1 and MLA in failed[0]
        assert "live read failed" in failed[0]
        assert "mirror" not in failed[0].lower()
        assert len(reported) == 1 and MLA in reported[0]
        assert "1 active" in reported[0]
        assert "mirror" not in reported[0].lower()

    def test_uses_a_short_timeout(self, read_only_client: TestClient) -> None:
        response, mock_live = self._get(read_only_client, return_value=[])

        assert response.status_code == 200
        timeout = mock_live.call_args.kwargs["timeout"]
        assert 0 < timeout <= 3.0


class TestClientTimeoutIsHonoured:
    def test_get_item_promotions_passes_the_timeout_to_httpx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        import httpx

        from app.services.ml_webhook_client import MLWebhookClient

        seen: Dict[str, Any] = {}
        original_init = httpx.AsyncClient.__init__

        def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            seen["timeout"] = kwargs.get("timeout")
            kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

        assert asyncio.run(MLWebhookClient().get_item_promotions(MLA, timeout=2.5)) == []
        assert seen["timeout"] == 2.5

    def test_slow_proxy_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A proxy slower than the timeout yields None quickly, never a hang."""
        import asyncio
        import time

        import httpx

        from app.services.ml_webhook_client import MLWebhookClient

        async def slow_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, json=[])

        original_init = httpx.AsyncClient.__init__

        def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(slow_handler)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

        started = time.monotonic()
        result = asyncio.run(MLWebhookClient().get_item_promotions(MLA, timeout=0.2))

        assert result is None
        assert time.monotonic() - started < 2.0


class TestHardDeadlineOnlyWhenExplicit:
    """`asyncio.wait_for` is a hard overall deadline: only an explicit
    `timeout=` may opt into it. Default callers (the enroll live re-read)
    keep httpx's per-phase timeout and are not cut short."""

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> list:
        import asyncio

        import httpx

        calls: list = []
        real_wait_for = asyncio.wait_for

        async def spy(aw: Any, timeout: Any = None) -> Any:
            calls.append(timeout)
            return await real_wait_for(aw, timeout)

        monkeypatch.setattr("app.services.ml_webhook_client.asyncio.wait_for", spy)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
        return calls

    def test_default_call_has_no_hard_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        from app.services.ml_webhook_client import MLWebhookClient

        calls = self._spy(monkeypatch)

        assert asyncio.run(MLWebhookClient().get_item_promotions(MLA)) == []
        assert calls == []

    def test_explicit_timeout_applies_the_hard_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        from app.services.ml_webhook_client import MLWebhookClient

        calls = self._spy(monkeypatch)

        assert asyncio.run(MLWebhookClient().get_item_promotions(MLA, timeout=2.5)) == []
        assert calls == [2.5]


# ── One offer-price rule (shared by guard, 409 and markup) ──────


class TestOfferPriceRule:
    def test_price_wins_when_positive(self) -> None:
        assert pricing.precio_de_oferta({"price": 100.0, "suggested_discounted_price": 90.0}) == 100.0

    def test_suggested_when_price_is_zero(self) -> None:
        assert pricing.precio_de_oferta({"price": 0, "suggested_discounted_price": 90.0}) == 90.0

    @pytest.mark.parametrize(
        "entry",
        [
            {},
            {"price": 0},
            {"price": None, "suggested_discounted_price": None},
            {"price": 0, "suggested_discounted_price": 0},
        ],
    )
    def test_none_when_neither_is_usable(self, entry: Dict[str, Any]) -> None:
        assert pricing.precio_de_oferta(entry) is None


@pytest.mark.usefixtures("writes_on")
class TestGuardUsesTheOfferPriceRule:
    def test_price_zero_with_suggested_compares_the_suggested(self) -> None:
        entry = _live_entry(price=0)
        entry["suggested_discounted_price"] = LIVE_PRICE
        proxy = FakeProxy([entry])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert result["status"] == "submitted"
        assert len(proxy.enrolls) == 1

    def test_price_zero_with_suggested_changed_reports_the_suggested(self) -> None:
        entry = _live_entry(price=0)
        entry["suggested_discounted_price"] = LIVE_PRICE
        proxy = FakeProxy([entry])

        result = _enroll(proxy, precio_visto=STALE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_price_changed"
        assert result["precio_actual"] == LIVE_PRICE

    def test_positive_price_ignores_a_different_suggested(self) -> None:
        entry = _live_entry(price=LIVE_PRICE)
        entry["suggested_discounted_price"] = STALE_PRICE
        proxy = FakeProxy([entry])

        result = _enroll(proxy, precio_visto=STALE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_price_changed"
        assert result["precio_actual"] == LIVE_PRICE

    def test_both_missing_is_blocked(self) -> None:
        entry = _live_entry(price=0)
        entry["suggested_discounted_price"] = None
        proxy = FakeProxy([entry])

        result = _enroll(proxy, precio_visto=LIVE_PRICE)

        assert proxy.enrolls == []
        assert result["status"] == "rejected_price_unresolved"

    def test_markup_of_a_live_offer_uses_the_same_price(self) -> None:
        captured: Dict[str, Any] = {}

        def _fake_enriquecer(db: Any, mla: str, promos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            captured.update(promos[0])
            promos[0]["nuestro_markup"] = 1.0
            return promos

        entry = _live_entry(price=0)
        entry["suggested_discounted_price"] = LIVE_PRICE
        with patch.object(pricing, "enriquecer_markup_por_promo", side_effect=_fake_enriquecer):
            pricing.markup_de_oferta_live(object(), MLA, "SMART", entry)

        assert pricing.precio_de_oferta(captured) == LIVE_PRICE


class TestNoPriceAlias:
    def test_pricing_module_has_a_single_offer_price_function(self) -> None:
        from app.services import ml_promotions_pricing

        assert not hasattr(ml_promotions_pricing, "_effective_discounted_price")
