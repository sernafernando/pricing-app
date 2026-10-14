"""The status the LIST needs (`status.build_list_status`) against the full report (`status.build_status`).

The list's honest-state block reads five things of the operator report: the flags, the kill switch, whether the
store has items, whether the items are stale and which resources are collected. The full report also scans the
queue, the jobs, every sub-resource state table, the events and the links coverage (about 1.5 s on a 25k-item
store), which the first request of every minute paid. `build_list_status` computes only the five, and the block built
from it must be the block built from the full report, whatever the state of the store.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_publications import settings_store, status
from app.services.ml_publications.view import status_block
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.test_status import put_item, run, store  # noqa: F401

pytestmark = pytest.mark.postgres

STORE_TABLES = {"ml_items"}


def list_report(engine) -> dict:
    session = sessionmaker(bind=engine)()
    try:
        return status.build_list_status(session)
    finally:
        session.close()


def full_report(engine) -> dict:
    session = sessionmaker(bind=engine)()
    try:
        return status.build_status(session)
    finally:
        session.close()


def blocks(engine) -> tuple[dict, dict]:
    lean, full = status_block.build_block(list_report(engine)), status_block.build_block(full_report(engine))
    for block in (lean, full):
        block.pop("generated_at")
        for degradation in block["degradations"]:  # the two reports read the clock a moment apart
            if "p95_age_seconds" in degradation:
                degradation["p95_age_seconds"] = round(degradation["p95_age_seconds"])
    return lean, full


class TestTheBlockIsTheOneOfTheFullReport:
    def test_an_empty_store(self, store) -> None:  # noqa: F811
        lean, full = blocks(store)
        assert lean == full and lean["store_empty"] is True

    def test_fresh_items(self, store) -> None:  # noqa: F811
        put_item(store, "MLA1")
        put_item(store, "MLA2", state="paused", checked="2 hours")
        lean, full = blocks(store)
        assert lean == full and lean["store_empty"] is False and lean["degradations"] == full["degradations"]

    def test_items_older_than_the_stale_window(self, store) -> None:  # noqa: F811
        for number in range(5):
            put_item(store, f"MLA{number}", checked="400 days")
        lean, full = blocks(store)
        assert lean == full
        assert [d["code"] for d in lean["degradations"] if d["code"] == "stale_data"] == ["stale_data"]

    def test_items_never_checked_are_not_stale(self, store) -> None:  # noqa: F811
        put_item(store, "MLA1", checked=None)
        lean, full = blocks(store)
        assert lean == full

    def test_a_disabled_flag_and_an_uncollected_resource(self, store) -> None:  # noqa: F811
        put_item(store, "MLA1")
        settings_store.set_setting("events.enabled", False, "test")
        settings_store.set_setting("bundle_resources", ["core", "description"], "test")
        lean, full = blocks(store)
        assert lean == full
        codes = {(d["code"], d.get("flag") or d.get("resource")) for d in lean["degradations"]}
        assert ("flag_disabled", "events") in codes and ("resource_not_collected", "stock") in codes

    def test_the_kill_switch(self, store, monkeypatch) -> None:  # noqa: F811
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        lean, full = blocks(store)
        assert lean == full and lean["kill_switch"] is True and lean["degraded"] is True


class TestWhatItReads:
    def test_it_reads_only_the_items_table_in_a_few_read_only_statements(self, store) -> None:  # noqa: F811
        """Structural: no queue, job, sub-resource, event, change-log or link scan."""
        put_item(store, "MLA1")
        recorded: list[str] = []

        def record(connection, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(store, "before_cursor_execute", record)
        try:
            list_report(store)
        finally:
            event.remove(store, "before_cursor_execute", record)
        read = {
            name for statement in recorded for name in re.findall(r"(?:FROM|JOIN)\s+((?:ml|worker)_\w+)", statement)
        }
        assert read - STORE_TABLES - {"ml_pub_settings"} == set(), read
        assert len(recorded) <= 12
        assert any("READ ONLY" in statement for statement in recorded)
        assert any("statement_timeout" in statement for statement in recorded)

    def test_a_failing_section_is_named_and_the_rest_still_answers(self, store, monkeypatch) -> None:  # noqa: F811
        def broken(db):
            raise RuntimeError("boom")

        monkeypatch.setattr(status, "_items", broken)
        report = list_report(store)
        assert report["sections_failed"] == ["items"] and report["items"] is None
        block = status_block.build_block(report)
        assert block["degraded"] is True and block["sections_failed"] == ["items"]
        run(store, "SELECT 1")  # the connection is still usable

    def test_the_block_cache_builds_from_it_and_never_from_the_full_report(self, monkeypatch) -> None:
        from contextlib import contextmanager

        class Session:
            def rollback(self) -> None:
                pass

        @contextmanager
        def background():
            yield Session()

        monkeypatch.setattr(status_block.database, "get_background_db", background)
        monkeypatch.setattr(status, "build_list_status", lambda session: {"marker": 1})
        monkeypatch.setattr(status, "build_status", lambda session: pytest.fail("the full report was scanned"))
        assert status_block._build_report() == {"marker": 1}
