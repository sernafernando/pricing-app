"""The ERP fetch must not run with a transaction open on the caller's session.

`sync_transacciones_incrementales` probes `max(ct_transaction)` to decide what to ask
the ERP for. That read opens a transaction; the HTTP call that follows targets our own
API (`/api/gbp-parser`) with `timeout=120.0` -- exactly the value of
`idle_in_transaction_session_timeout`. Holding the session across it pins a PgBouncer
server connection for the whole round-trip while the request we issue consumes a second
connection from the API pool, and a slow ERP gets the session killed at the boundary.

Same defect class as the 2026-09-16 `POST /sync` incident.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.scripts import sync_commercial_transactions_incremental as mod


def _session_recording_into(calls: list[str], ultimo_ct: int | None) -> MagicMock:
    db = MagicMock()
    db.commit.side_effect = lambda: calls.append("commit")
    db.rollback.side_effect = lambda: calls.append("rollback")
    db.query.return_value.scalar.side_effect = lambda: calls.append("probe") or ultimo_ct
    return db


def _client_recording_into(calls: list[str], payload: list) -> MagicMock:
    """An httpx.AsyncClient stand-in that logs when the request is issued."""

    async def _get(*args, **kwargs):
        calls.append("http")
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value=payload)
        return response

    client = MagicMock()
    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_commits_caller_session_before_erp_http_call():
    calls: list[str] = []
    db = _session_recording_into(calls, ultimo_ct=1000)

    # Empty payload -> returns right after the fetch, before any write path.
    with patch.object(mod.httpx, "AsyncClient", return_value=_client_recording_into(calls, [])):
        asyncio.run(mod.sync_transacciones_incrementales(db))

    assert "probe" in calls, "the max(ct_transaction) probe never ran"
    assert "http" in calls, "the ERP fetch never ran"
    assert "commit" in calls, "caller session was never committed"
    assert calls.index("commit") < calls.index("http"), (
        f"caller session still had an open transaction during the ERP HTTP call: {calls}"
    )
    assert calls.index("probe") < calls.index("commit"), (
        f"the probe must run before the release, otherwise it reopens a transaction: {calls}"
    )


def test_bails_out_without_http_when_table_is_empty():
    """No baseline row -> the script must not query the ERP at all."""
    calls: list[str] = []
    db = _session_recording_into(calls, ultimo_ct=None)

    with patch.object(mod.httpx, "AsyncClient", return_value=_client_recording_into(calls, [])):
        result = asyncio.run(mod.sync_transacciones_incrementales(db))

    assert result == (0, 0, 0)
    assert "http" not in calls, "queried the ERP despite having no baseline ct_transaction"
