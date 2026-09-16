"""Regression tests for the 2026-09-16 connection-pool exhaustion incident.

`POST /sync` held its request-scoped session open across a `requests.get(timeout=300)`
to the ERP. The session sat `idle in transaction` for the whole round-trip, holding one
of the 25 available pool connections; under concurrency the pool drained and every other
request failed with `QueuePool limit of size 15 overflow 10 reached`. PostgreSQL then
terminated the stalled connections via `idle_in_transaction_session_timeout`.

The contract these tests pin down: no transaction may be open on the caller's session
while the ERP is being queried over HTTP.
"""

from unittest.mock import MagicMock, patch

from app.scripts import sync_price_list_items as mod


def _session_recording_into(calls: list[str]) -> MagicMock:
    """A session mock that appends every relevant call to a shared ordering log."""
    db = MagicMock()
    db.commit.side_effect = lambda: calls.append("commit")
    db.rollback.side_effect = lambda: calls.append("rollback")
    db.query.side_effect = lambda *a, **kw: calls.append("query") or MagicMock()
    return db


def test_incremental_commits_caller_session_before_erp_http_call():
    calls: list[str] = []
    db = _session_recording_into(calls)

    with (
        patch.object(mod, "get_background_db") as background_db,
        patch.object(mod, "fetch_price_list_items_from_erp") as fetch,
    ):
        probe = MagicMock()
        probe.query.return_value.filter.return_value.scalar.return_value = None
        background_db.return_value.__enter__.return_value = probe

        fetch.side_effect = lambda *a, **kw: calls.append("http") or []

        mod.sync_price_list_items_incremental(db, price_list_id=4)

    assert "http" in calls, "the ERP fetch never ran"
    assert "commit" in calls, "caller session was never committed"
    assert calls.index("commit") < calls.index("http"), (
        f"caller session still had an open transaction during the ERP HTTP call: {calls}"
    )


def test_incremental_probes_freshness_on_its_own_session():
    """The max(prli_updatedAt) probe must not open a transaction on the caller's session."""
    calls: list[str] = []
    db = _session_recording_into(calls)

    with (
        patch.object(mod, "get_background_db") as background_db,
        patch.object(mod, "fetch_price_list_items_from_erp", return_value=[]),
    ):
        probe = MagicMock()
        probe.query.return_value.filter.return_value.scalar.return_value = None
        background_db.return_value.__enter__.return_value = probe

        mod.sync_price_list_items_incremental(db, price_list_id=4)

    background_db.assert_called_once()
    probe.query.assert_called_once()
    db.query.assert_not_called()


def test_incremental_skips_probe_when_update_from_is_given():
    with (
        patch.object(mod, "get_background_db") as background_db,
        patch.object(mod, "fetch_price_list_items_from_erp", return_value=[]) as fetch,
    ):
        mod.sync_price_list_items_incremental(MagicMock(), price_list_id=4, update_from="2026-09-16T00:00:00")

    background_db.assert_not_called()
    assert fetch.call_args.kwargs["update_from"] == "2026-09-16T00:00:00"


def test_sync_all_commits_caller_session_before_erp_http_call():
    calls: list[str] = []
    db = _session_recording_into(calls)

    with patch.object(mod, "fetch_price_list_items_from_erp") as fetch:
        fetch.side_effect = lambda *a, **kw: calls.append("http") or []
        mod.sync_price_list_items_all(db, price_list_id=4)

    assert calls.index("commit") < calls.index("http"), (
        f"caller session still had an open transaction during the ERP HTTP call: {calls}"
    )
