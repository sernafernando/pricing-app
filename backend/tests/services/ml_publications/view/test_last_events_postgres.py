"""The last event of each listed publication (`listing._last_events`).

It used to be a `DISTINCT ON (item_id)` over every event of the page's items: the server read ALL the events of each
item to keep one (400k events of ten busy items: 173 ms, against 0.1 ms for one index probe per item), and the items
that sort first by markup are often the busiest. The same answer comes from one probe per item.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.services.ml_publications.view import listing
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres


@pytest.fixture()
def conn(env):  # noqa: F811
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_the_newest_event_of_each_item_and_none_for_an_item_without_events(conn, db) -> None:
    for item_id in ("MLA1", "MLA2", "MLA3"):
        seed.add_item(conn, item_id)
    seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(5))
    seed.add_event(conn, "MLA1", "status_changed", seed.hours_ago(1))
    seed.add_event(conn, "MLA1", "stock_changed", seed.hours_ago(9))
    seed.add_event(conn, "MLA2", "price_changed", seed.hours_ago(3))
    found = listing._last_events(db, ["MLA1", "MLA2", "MLA3"])
    assert found == {
        "MLA1": {"event_type": "status_changed", "observed_at": seed.hours_ago(1)},
        "MLA2": {"event_type": "price_changed", "observed_at": seed.hours_ago(3)},
    }


def test_events_at_the_same_instant_are_ordered_by_id_and_the_newest_row_wins(conn, db) -> None:
    seed.add_item(conn, "MLA1")
    seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(2))
    seed.add_event(conn, "MLA1", "status_changed", seed.hours_ago(2))
    assert listing._last_events(db, ["MLA1"])["MLA1"]["event_type"] == "status_changed"


def test_no_ids_no_answer(conn, db) -> None:
    assert listing._last_events(db, []) == {}


def test_it_probes_each_item_instead_of_reading_all_of_its_events(conn, db) -> None:
    """Structural: one statement, a LATERAL probe with LIMIT 1 per id, and no DISTINCT over the events."""
    seed.add_item(conn, "MLA1")
    seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(2))
    recorded: list[str] = []

    def record(connection, cursor, statement, *rest) -> None:
        recorded.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        listing._last_events(db, ["MLA1", "MLA2"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert len(recorded) == 1
    assert "LATERAL" in recorded[0] and "LIMIT" in recorded[0] and "DISTINCT" not in recorded[0].upper()


def test_repeated_ids_are_probed_once(conn, db) -> None:
    seed.add_item(conn, "MLA1")
    seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(2))
    recorded: list[tuple] = []

    def record(connection, cursor, statement, parameters, *rest) -> None:
        recorded.append(parameters)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        found = listing._last_events(db, ["MLA1", "MLA1", "MLA1"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert list(found) == ["MLA1"] and ["MLA1"] in list(recorded[0].values())
