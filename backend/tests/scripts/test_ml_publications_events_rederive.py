"""Operator CLI that rebuilds business events from the stored change log.

Postgres only. It never calls ML and never needs current state.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from app.scripts import ml_publications_events_rederive
from app.services.ml_publications import ml_http
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import mlpub_pg, sample_item  # noqa: F401  (fixture re-export)
from tests.services.ml_publications.test_store_apply_fetch import ACTIVE, apply

pytestmark = pytest.mark.postgres


def event_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM ml_item_events")).scalar()


@pytest.fixture()
def paused_item(mlpub_pg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        ml_http.MlHttpClient, "__init__", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ML client"))
    )
    set_setting("events.enabled", True, "test")
    body = sample_item(ACTIVE)
    apply(body, ACTIVE, minutes=1)
    changed = copy.deepcopy(body)
    changed["status"] = "paused"
    apply(changed, ACTIVE, minutes=2)
    return mlpub_pg


class TestRederiveCli:
    def test_rebuilds_deleted_events_and_reports_the_count(self, paused_item, capsys) -> None:
        with paused_item.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_events"))

        assert ml_publications_events_rederive.main([]) == 0

        assert event_count(paused_item) == 1
        assert "created 1 event" in capsys.readouterr().out

    def test_is_a_no_op_when_the_events_exist(self, paused_item, capsys) -> None:
        assert ml_publications_events_rederive.main([]) == 0
        assert event_count(paused_item) == 1 and "created 0 events" in capsys.readouterr().out

    def test_can_be_limited_to_one_item(self, paused_item, capsys) -> None:
        with paused_item.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_events"))
        assert ml_publications_events_rederive.main(["--item", "MLA_OTHER"]) == 0
        assert event_count(paused_item) == 0
        assert ml_publications_events_rederive.main(["--item", ACTIVE]) == 0
        assert event_count(paused_item) == 1

    def test_rejects_a_non_positive_batch_size(self, paused_item) -> None:
        assert ml_publications_events_rederive.main(["--batch-size", "0"]) == 2

    def test_rejects_a_batch_size_above_the_cap(self, paused_item, capsys) -> None:
        from app.services.ml_publications import events_store

        assert ml_publications_events_rederive.main(["--batch-size", str(events_store.MAX_BATCH_SIZE + 1)]) == 2
        assert "at most" in capsys.readouterr().err
