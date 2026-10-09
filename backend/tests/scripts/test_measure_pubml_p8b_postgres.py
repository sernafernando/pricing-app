"""P8b.T3: the statements `scripts/measure_pubml_p8b.py` picks its publications with, run on the real store schema.

The script is run once, on production data, by a person: a statement that fails there costs a whole round trip, so
each is exercised here against the tables the migrations build. Rows are dated relative to now: the pickers look at
the last 30 days.
"""

# ruff: noqa: F811 -- the fixture is imported and used by name

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p8b.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p8b_pg", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def pick(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def days_ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_each_statement_picks_the_publication_it_is_named_for(script, mlpub_pg) -> None:
    with mlpub_pg.begin() as conn:
        for item_id in ("MLA1", "MLA2", "MLA3"):
            seed.add_item(conn, item_id)
        for n in range(3):  # MLA1: three events, the busiest; the most recent one is MLA2's
            seed.add_event(conn, "MLA1", "price_changed", days_ago(5 + n))
        seed.add_event(conn, "MLA2", "price_changed", days_ago(0.1))
        seed.add_event(conn, "MLA3", "price_changed", days_ago(90))  # old: outside the window of "busiest"
        for n in range(5):
            seed.add_event(conn, "MLA3", "price_changed", days_ago(90 + n))
    assert pick(mlpub_pg, script.BUSIEST_SQL["events"]) == "MLA1"
    assert pick(mlpub_pg, script.RECENT_SQL["events"]) == "MLA2"
    # the seeded events carry a change-log row each (see `seed.add_event`): the same publications for the history
    assert pick(mlpub_pg, script.BUSIEST_SQL["history"]) == "MLA1"
    assert pick(mlpub_pg, script.RECENT_SQL["history"]) == "MLA2"


def test_ties_are_broken_by_the_item_id_in_byte_order(script, mlpub_pg) -> None:
    with mlpub_pg.begin() as conn:
        for item_id in ("MLA20", "MLA3"):  # "MLA20" < "MLA3" in byte order, whatever the database collation
            seed.add_item(conn, item_id)
            seed.add_event(conn, item_id, "price_changed", days_ago(1))
    assert pick(mlpub_pg, script.BUSIEST_SQL["events"]) == "MLA20"


def test_an_empty_store_picks_nothing(script, mlpub_pg) -> None:
    for sql in (*script.BUSIEST_SQL.values(), *script.RECENT_SQL.values()):
        assert pick(mlpub_pg, sql) is None
