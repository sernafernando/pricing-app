"""Turbo routing geocoding endpoints must not hold a DB session across HTTP calls.

All three endpoints in `turbo_routing/geocoding.py` took a request-scoped session via
`Depends(get_async_db)`, opened a transaction on it at the permission check, and never
read from it again — leaving it `idle in transaction` for the whole request. `batch`
was the worst: it also kept a `get_background_db()` session open *around* each Mapbox
call, so a 100-item batch held two connections for its entire duration.

Same defect class as the 2026-09-16 `POST /sync` incident.
"""

import asyncio
from contextlib import contextmanager
from typing import Generator, List
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.endpoints.turbo_routing import geocoding as mod


def _tracking_bg_db(events: List[str], session: MagicMock):
    """A get_background_db stand-in that records when a short session opens/closes."""

    @contextmanager
    def _cm() -> Generator[MagicMock, None, None]:
        events.append("open")
        try:
            yield session
        finally:
            events.append("close")

    return _cm


def _envio(street="Calle Falsa", number="123", city="Buenos Aires") -> MagicMock:
    e = MagicMock()
    e.mlstreet_name = street
    e.mlstreet_number = number
    e.mlcity_name = city
    return e


def _request_session(events: List[str]) -> MagicMock:
    db = MagicMock()
    db.commit.side_effect = lambda: events.append("request_commit")
    return db


def test_batch_holds_no_session_during_mapbox_calls():
    events: List[str] = []
    bg = MagicMock()
    bg.query.return_value.filter.return_value.first.return_value = _envio()

    async def _geocode(*args, **kwargs):
        events.append("http")
        assert events.count("open") == events.count("close"), (
            f"a get_background_db() session was still open during the HTTP call: {events}"
        )
        assert kwargs.get("db") is None, "geocode_address must not receive our session"
        return (-34.6, -58.4)

    with (
        patch.object(mod, "get_background_db", _tracking_bg_db(events, bg)),
        patch.object(mod, "verificar_permiso", return_value=True),
        patch.object(mod, "geocode_address", side_effect=_geocode),
        patch.object(mod.asyncio, "sleep", new=AsyncMock()),
    ):
        asyncio.run(mod.geocodificar_batch(["S1", "S2"], db=_request_session(events), current_user={}))

    assert events.count("http") == 2
    assert "request_commit" in events, "the request session was never released"
    assert events.index("request_commit") < events.index("http"), (
        f"request session still had an open transaction during the HTTP calls: {events}"
    )


def test_batch_preserves_caller_order_in_detalles():
    """`detalles` must follow `shipment_ids`, even when failures and successes mix."""
    events: List[str] = []
    bg = MagicMock()
    # S2 is missing from the DB -> resolved in phase 1, before any HTTP happens.
    bg.query.return_value.filter.return_value.first.side_effect = [_envio(), None, _envio()]

    async def _geocode(*args, **kwargs):
        return (-34.6, -58.4)

    with (
        patch.object(mod, "get_background_db", _tracking_bg_db(events, bg)),
        patch.object(mod, "verificar_permiso", return_value=True),
        patch.object(mod, "geocode_address", side_effect=_geocode),
        patch.object(mod.asyncio, "sleep", new=AsyncMock()),
    ):
        res = asyncio.run(mod.geocodificar_batch(["S1", "S2", "S3"], db=_request_session(events), current_user={}))

    assert [d["shipment_id"] for d in res["detalles"]] == ["S1", "S2", "S3"]
    assert res["exitosos"] == 2
    assert res["fallidos"] == 1
    assert res["total"] == 3


def test_batch_counts_failed_geocoding_without_writing():
    events: List[str] = []
    bg = MagicMock()
    bg.query.return_value.filter.return_value.first.return_value = _envio()

    async def _geocode(*args, **kwargs):
        return None

    with (
        patch.object(mod, "get_background_db", _tracking_bg_db(events, bg)),
        patch.object(mod, "verificar_permiso", return_value=True),
        patch.object(mod, "geocode_address", side_effect=_geocode),
        patch.object(mod.asyncio, "sleep", new=AsyncMock()),
    ):
        res = asyncio.run(mod.geocodificar_batch(["S1"], db=_request_session(events), current_user={}))

    assert res["fallidos"] == 1
    assert res["exitosos"] == 0
    assert res["detalles"][0]["mensaje"] == "No se pudo geocodificar"
    # Phase 3 must be skipped entirely when nothing geocoded: one open (phase 1) only.
    assert events.count("open") == 1, f"opened a write session with nothing to write: {events}"


def test_batch_skips_envios_without_address():
    events: List[str] = []
    bg = MagicMock()
    bg.query.return_value.filter.return_value.first.return_value = _envio(street=None, number=None)

    async def _geocode(*args, **kwargs):
        events.append("http")
        return (-34.6, -58.4)

    with (
        patch.object(mod, "get_background_db", _tracking_bg_db(events, bg)),
        patch.object(mod, "verificar_permiso", return_value=True),
        patch.object(mod, "geocode_address", side_effect=_geocode),
        patch.object(mod.asyncio, "sleep", new=AsyncMock()),
    ):
        res = asyncio.run(mod.geocodificar_batch(["S1"], db=_request_session(events), current_user={}))

    assert res["fallidos"] == 1
    assert res["detalles"][0]["mensaje"] == "Sin dirección válida"
    assert "http" not in events, "geocoded an envío that had no address"


def test_envio_individual_releases_session_before_http():
    events: List[str] = []
    db = _request_session(events)
    db.query.return_value.filter.return_value.first.return_value = _envio()

    async def _geocode(*args, **kwargs):
        events.append("http")
        assert kwargs.get("db") is None, "geocode_address must not receive the request session"
        return (-34.6, -58.4)

    with (
        patch.object(mod, "verificar_permiso", return_value=True),
        patch.object(mod, "geocode_address", side_effect=_geocode),
    ):
        asyncio.run(mod.geocodificar_envio("S1", db=db, current_user={}))

    assert events.index("request_commit") < events.index("http"), (
        f"request session still had an open transaction during the HTTP call: {events}"
    )
