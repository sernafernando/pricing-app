"""Integration tests for `GET /pxq/{item_id}/live` (PR 3b, tasks 51-55).

Pool-safety is the point of this endpoint (design "Live-Read Endpoint
(pool-safe)"; `backend/CLAUDE.md`'s QueuePool-exhaustion rule): the DB
session used to load the local mirror MUST be closed before the ML proxy
call runs. That is proven directly by calling the endpoint function with a
spy `get_background_db` and asserting session-close happened before the
mocked proxy call.

No `pytest-asyncio` plugin is installed in this repo (see
`test_ml_webhook_client_catalog_competition.py`) -- async endpoints are
exercised via `asyncio.run(...)` from plain sync test functions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.routers import pxq as pxq_router


class _FakeUsuario:
    es_superadmin = True


class _SpyDb:
    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return []


def _cm_with_hook(on_exit=None):
    class _CM:
        def __enter__(self):
            return _SpyDb()

        def __exit__(self, *exc):
            if on_exit is not None:
                on_exit()
            return False

    return _CM()


def test_session_closes_before_the_proxy_call(monkeypatch) -> None:
    call_order: list[str] = []
    monkeypatch.setattr(
        pxq_router, "get_background_db", lambda: _cm_with_hook(lambda: call_order.append("db_session_closed"))
    )

    async def _fake_get_pxq_prices(item_id):
        call_order.append("proxy_call")
        return [{"id": "ML1", "quantity": 10, "amount": 500.0}]

    async def _run():
        with patch.object(pxq_router.ml_webhook_client, "get_pxq_prices", side_effect=_fake_get_pxq_prices):
            with patch.object(pxq_router, "_require_pxq_read", return_value=None):
                return await pxq_router.obtener_estado_live_pxq(item_id="MLA1", current_user=_FakeUsuario())

    response = asyncio.run(_run())

    assert call_order == ["db_session_closed", "proxy_call"]
    assert response.live_status == "ok"
    assert response.live_tiers[0].id == "ML1"


def test_live_unavailable_returns_ok_response_with_null_tiers(monkeypatch) -> None:
    monkeypatch.setattr(pxq_router, "get_background_db", lambda: _cm_with_hook())

    async def _run():
        with patch.object(pxq_router.ml_webhook_client, "get_pxq_prices", AsyncMock(return_value=None)):
            with patch.object(pxq_router, "_require_pxq_read", return_value=None):
                return await pxq_router.obtener_estado_live_pxq(item_id="MLA1", current_user=_FakeUsuario())

    response = asyncio.run(_run())

    assert response.live_status == "unavailable"
    assert response.live_tiers is None


def test_two_consecutive_calls_both_hit_the_proxy_never_cached(monkeypatch) -> None:
    monkeypatch.setattr(pxq_router, "get_background_db", lambda: _cm_with_hook())
    proxy_mock = AsyncMock(return_value=[{"id": "ML1", "quantity": 10, "amount": 500.0}])

    async def _run():
        with patch.object(pxq_router.ml_webhook_client, "get_pxq_prices", proxy_mock):
            with patch.object(pxq_router, "_require_pxq_read", return_value=None):
                await pxq_router.obtener_estado_live_pxq(item_id="MLA1", current_user=_FakeUsuario())
                return await pxq_router.obtener_estado_live_pxq(item_id="MLA1", current_user=_FakeUsuario())

    r2 = asyncio.run(_run())

    assert proxy_mock.await_count == 2
    assert isinstance(r2.fetched_at, datetime)
    assert r2.fetched_at.tzinfo is not None


def test_live_tier_accepts_a_numeric_id_from_the_proxy():
    """The write service already does str(entry["id"]) on this same payload,
    so a numeric id was known to be possible. Pydantic v2 does not coerce
    int to str, so the read path raised ValidationError and answered 500 —
    the opposite of the fail-closed behaviour its docstring promises."""
    from app.routers.pxq import _parse_live_tiers

    tiers = _parse_live_tiers([{"id": 12345, "quantity": 10, "amount": "500.00"}])

    assert tiers is not None
    assert tiers[0].id == "12345"
    assert tiers[0].quantity == 10


def test_divergence_response_carries_the_divergences_not_just_a_label():
    """Spec: the write is refused AND the divergence is displayed for manual
    resolution. Collapsing the outcome to detail="divergence" throws away the
    live-vs-desired payload PR 4 needs to render the conflict."""
    from app.routers.pxq import _error_detail_from_outcome

    outcome = {
        "status": "divergence",
        "reason": "divergence",
        "divergences": [
            {"ml_price_id": "ML1", "reason": "live changed since the last sync"},
        ],
    }

    detail = _error_detail_from_outcome(outcome)

    assert detail["status"] == "divergence"
    assert detail["divergences"][0]["ml_price_id"] == "ML1"


def test_a_malformed_live_entry_degrades_instead_of_raising():
    """The endpoint promises to answer 200 with live_status='unavailable' when
    the live read cannot be trusted. Switching a KeyError for a
    ValidationError changed which exception surfaced, not the outcome — both
    still reached the client as a 500."""
    from app.routers.pxq import _parse_live_tiers

    assert _parse_live_tiers([{"id": 1, "quantity": 10}]) is None
    assert _parse_live_tiers([{"quantity": 10, "amount": "500.00"}]) is None
    assert _parse_live_tiers(None) is None


def test_a_well_formed_live_payload_parses():
    from app.routers.pxq import _parse_live_tiers

    tiers = _parse_live_tiers([{"id": 7, "quantity": 10, "amount": "500.00"}])

    assert tiers is not None
    assert tiers[0].id == "7"


def test_a_non_numeric_amount_degrades_instead_of_raising():
    """decimal.InvalidOperation derives from ArithmeticError, not ValueError,
    so a junk amount escaped the except and answered 500 — the very defect the
    surrounding docstring claims to have closed."""
    from app.routers.pxq import _parse_live_tiers

    assert _parse_live_tiers([{"id": 1, "quantity": 10, "amount": "N/A"}]) is None


def test_unavailable_from_a_bad_payload_returns_null_tiers_not_an_empty_list():
    """`live_tiers=[]` states that MercadoLibre has no tiers. That is a claim,
    and we do not have it — the read failed. The `live_raw is None` branch
    already returned None; the parse-failure branch invented an empty list, so
    a client would render "0 live tiers" instead of "could not read"."""
    from datetime import datetime, timezone

    from app.routers.pxq import _unavailable_response

    response = _unavailable_response(item_id="MLA1", mirror_tiers=[], fetched_at=datetime.now(timezone.utc))

    assert response.live_status == "unavailable"
    assert response.live_tiers is None


def test_read_permission_gate_actually_runs_against_a_real_user(db, rol_ventas):
    """`_require_pxq_read` is the only security control on this endpoint, and
    every existing test patched it out — so the one thing protecting live ML
    data from an unauthorized reader was never executed.

    It also runs with a user loaded by `get_current_user_transient`, i.e.
    detached from the session that produced it, which is exactly the shape
    that raises DetachedInstanceError if the permission lookup touches a lazy
    relationship."""
    import pytest
    from fastapi import HTTPException

    from app.core.security import get_password_hash
    from app.models.usuario import AuthProvider, RolUsuario, Usuario
    from app.routers.pxq import _require_pxq_read

    user = Usuario(
        username="pxq_no_access",
        email="pxq_no_access@example.com",
        nombre="No Access",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.expunge(user)  # detached, as the transient dependency returns it

    with pytest.raises(HTTPException) as exc:
        _require_pxq_read(user, db)

    assert exc.value.status_code == 403


class TestKillSwitchIsDistinguishableFromPermissionDenial:
    """A user WITH permission hitting a disabled feature, and a user WITHOUT
    permission, must not receive the same answer — the frontend cannot tell
    "ask an admin for access" from "this is turned off" if both are 403."""

    def test_disabled_does_not_map_to_forbidden(self) -> None:
        from app.routers.pxq import _SYNC_STATUS_TO_HTTP

        assert _SYNC_STATUS_TO_HTTP["disabled"] != 403
        assert _SYNC_STATUS_TO_HTTP["disabled"] == 503

    def test_every_non_success_status_has_an_http_mapping(self) -> None:
        """Derived from the service's own declaration, not a copy. The set used
        to be hardcoded here, so the test that exists to catch an unmapped
        status could not see a status the service had just added — which is
        exactly how `submitted_unconfirmed` reached callers as a 200."""
        from app.routers.pxq import _SYNC_STATUS_TO_HTTP
        from app.services.ml_pxq_write_service import SYNC_STATUSES

        unmapped = (SYNC_STATUSES - {"sincronizado"}) - set(_SYNC_STATUS_TO_HTTP)

        assert not unmapped, f"these fall through to 200 OK: {sorted(unmapped)}"
