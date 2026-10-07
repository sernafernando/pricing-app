"""Read interface over `ml_item_events` (spec "Event queryability").

Postgres only. Events are inserted directly with chosen timestamps so ordering and
pagination are exact; the store-attribution case goes through `apply_fetch` so the item's
own state row is real.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications import events_query
from app.services.ml_publications import store as store_module
from app.services.ml_publications.events import dedupe_key
from app.services.ml_publications.events_query import Cursor
from tests.services.ml_publications.conftest import sample_item
from tests.services.ml_publications.test_store_apply_fetch import ACTIVE, apply

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
MARVO_STORE = 57997


def day(n: float) -> datetime:
    return T0 + timedelta(days=n)


_counter = itertools.count(1)


def add_event(
    engine,
    item_id: str,
    event_type: str,
    observed_at: datetime,
    *,
    store: int | None = MARVO_STORE,
    brand: str | None = "Marvo",
    old=None,
    new=None,
) -> int:
    """One change-log row plus one event over it; returns the event id."""
    with engine.begin() as conn:
        log_id = conn.execute(
            text(
                "INSERT INTO ml_change_log (resource_type, entity_id, item_id, observed_at, changed_paths, changes)"
                " VALUES ('item', :i, :i, :t, '{}', '[]') RETURNING id"
            ),
            {"i": item_id, "t": observed_at},
        ).scalar()
        return conn.execute(
            text(
                "INSERT INTO ml_item_events (event_type, item_id, old_value, new_value, observed_at,"
                " official_store_id, brand, change_log_id, dedupe_key)"
                " VALUES (:et, :i, CAST(:o AS jsonb), CAST(:n AS jsonb), :t, :s, :b, :c, :k) RETURNING id"
            ),
            {
                "et": event_type,
                "i": item_id,
                "o": None if old is None else f'"{old}"',
                "n": None if new is None else f'"{new}"',
                "t": observed_at,
                "s": store,
                "b": brand,
                "c": log_id,
                "k": dedupe_key(log_id, event_type, None, f"u{next(_counter)}"),
            },
        ).scalar()


def pages(fetch, **kwargs):
    """Walk every page with the cursor; returns the list of pages."""
    out, cursor = [], None
    while True:
        page = fetch(cursor=cursor, **kwargs)
        out.append(page)
        if page.next_cursor is None:
            return out
        cursor = page.next_cursor


@pytest.fixture
def db(mlpub_pg):
    with store_module.database.get_background_db() as session:
        yield session


class TestItemTimeline:
    def test_returns_the_item_events_in_chronological_order_with_values(self, mlpub_pg, db) -> None:
        add_event(mlpub_pg, "MLA1", "status_activated", day(3), old="paused", new="active")
        add_event(mlpub_pg, "MLA1", "status_paused", day(1), old="active", new="paused")
        add_event(mlpub_pg, "MLA1", "title_changed", day(2), old="a", new="b")
        add_event(mlpub_pg, "MLA2", "status_paused", day(1))

        page = events_query.item_timeline(db, "MLA1")

        assert [e.event_type for e in page.events] == ["status_paused", "title_changed", "status_activated"]
        assert (page.events[0].old_value, page.events[0].new_value) == ("active", "paused")
        assert {e.item_id for e in page.events} == {"MLA1"} and page.next_cursor is None

    def test_newest_first_is_available(self, mlpub_pg, db) -> None:
        for n in (1, 2, 3):
            add_event(mlpub_pg, "MLA1", "status_paused", day(n))
        page = events_query.item_timeline(db, "MLA1", newest_first=True)
        assert [e.observed_at for e in page.events] == [day(3), day(2), day(1)]

    def test_paginates_without_skip_or_duplicate(self, mlpub_pg, db) -> None:
        ids = [add_event(mlpub_pg, "MLA1", "status_paused", day(n)) for n in range(5)]
        walked = pages(lambda cursor: events_query.item_timeline(db, "MLA1", limit=2, cursor=cursor))
        assert [len(p.events) for p in walked] == [2, 2, 1]
        assert [e.id for p in walked for e in p.events] == ids

    def test_events_sharing_a_timestamp_page_by_id(self, mlpub_pg, db) -> None:
        ids = [add_event(mlpub_pg, "MLA1", "status_paused", day(1)) for _ in range(5)]
        walked = pages(lambda cursor: events_query.item_timeline(db, "MLA1", limit=2, cursor=cursor))
        assert [e.id for p in walked for e in p.events] == ids


class TestByTypeAndRange:
    def test_only_the_type_inside_the_range_returns(self, mlpub_pg, db) -> None:
        inside = add_event(mlpub_pg, "MLA1", "status_paused", day(2))
        add_event(mlpub_pg, "MLA2", "status_paused", day(0))  # before
        add_event(mlpub_pg, "MLA3", "status_paused", day(5))  # at `until`: exclusive
        add_event(mlpub_pg, "MLA4", "status_activated", day(2))  # other type
        also = add_event(mlpub_pg, "MLA5", "status_paused", day(1))  # at `since`: inclusive

        page = events_query.search_events(db, event_type="status_paused", since=day(1), until=day(5))

        assert [e.id for e in page.events] == [inside, also]  # newest first

    def test_paginates_stably_newest_first(self, mlpub_pg, db) -> None:
        ids = [add_event(mlpub_pg, f"MLA{n}", "status_paused", day(n)) for n in range(5)]
        walked = pages(
            lambda cursor: events_query.search_events(db, event_type="status_paused", limit=2, cursor=cursor)
        )
        assert [e.id for p in walked for e in p.events] == list(reversed(ids))


class TestByStoreAndBrand:
    def test_filters_use_the_denormalized_store_and_brand(self, mlpub_pg, db) -> None:
        match = add_event(mlpub_pg, "MLA1", "promotion_activated", day(1), store=57997, brand="Marvo")
        add_event(mlpub_pg, "MLA2", "promotion_activated", day(1), store=57997, brand="Other")
        add_event(mlpub_pg, "MLA3", "promotion_activated", day(1), store=2645, brand="Marvo")
        add_event(mlpub_pg, "MLA4", "status_paused", day(1), store=57997, brand="Marvo")

        page = events_query.search_events(db, event_type="promotion_activated", official_store_id=57997, brand="Marvo")

        assert [e.id for e in page.events] == [match]

    def test_a_store_alone_returns_every_type(self, mlpub_pg, db) -> None:
        add_event(mlpub_pg, "MLA1", "promotion_activated", day(1), store=2645)
        add_event(mlpub_pg, "MLA2", "status_paused", day(2), store=2645)
        add_event(mlpub_pg, "MLA3", "status_paused", day(2), store=57997)
        page = events_query.search_events(db, official_store_id=2645)
        assert {e.item_id for e in page.events} == {"MLA1", "MLA2"}

    def test_the_old_store_still_matches_after_the_item_changes_store(self, mlpub_pg, db) -> None:
        """real item (store 57997) paused, then its state row moves to another store."""
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        before = add_event(mlpub_pg, ACTIVE, "status_paused", day(1), store=57997)
        with mlpub_pg.begin() as conn:
            conn.execute(text("UPDATE ml_items SET official_store_id = 1 WHERE item_id = :i"), {"i": ACTIVE})
        after = add_event(mlpub_pg, ACTIVE, "status_activated", day(2), store=1)

        old = events_query.search_events(db, official_store_id=57997)
        new = events_query.search_events(db, official_store_id=1)

        assert [e.id for e in old.events] == [before] and [e.id for e in new.events] == [after]

    def test_an_unscoped_search_is_refused(self, db) -> None:
        with pytest.raises(ValueError, match="event_type or official_store_id"):
            events_query.search_events(db, brand="Marvo", since=day(0))


class TestPaginationStability:
    def test_events_written_between_pages_cause_no_skip_and_no_duplicate(self, mlpub_pg, db) -> None:
        original = [add_event(mlpub_pg, f"MLA{n}", "status_paused", day(n)) for n in range(1, 6)]

        first = events_query.search_events(db, event_type="status_paused", limit=2)
        add_event(mlpub_pg, "MLA9", "status_paused", day(9))  # newer than everything
        add_event(mlpub_pg, "MLA8", "status_paused", day(4))  # same instant as an unread row, higher id
        rest = pages(
            lambda cursor: events_query.search_events(db, event_type="status_paused", limit=2, cursor=cursor),
        )  # a fresh walk sees everything exactly once
        second = events_query.search_events(db, event_type="status_paused", limit=2, cursor=first.next_cursor)
        third = events_query.search_events(db, event_type="status_paused", limit=2, cursor=second.next_cursor)

        seen = [e.id for page in (first, second, third) for e in page.events]
        assert [i for i in seen if i in original] == list(reversed(original))
        assert len(seen) == len(set(seen))
        assert len([e for p in rest for e in p.events]) == 7


class TestLimits:
    @pytest.mark.parametrize("limit", [0, -1])
    def test_a_non_positive_limit_is_refused(self, db, limit) -> None:
        with pytest.raises(ValueError, match="limit"):
            events_query.item_timeline(db, "MLA1", limit=limit)

    def test_the_limit_is_capped(self, mlpub_pg, db) -> None:
        for n in range(3):
            add_event(mlpub_pg, "MLA1", "status_paused", day(n))
        page = events_query.item_timeline(db, "MLA1", limit=events_query.MAX_LIMIT * 10)
        assert len(page.events) == 3

    def test_a_cursor_is_a_plain_value_pair(self) -> None:
        assert Cursor(day(1), 3) == Cursor(day(1), 3)


class TestIndexUse:
    """The three documented access paths run on their own index (seq scans disabled so the
    small test table cannot hide a missing or unusable index)."""

    @pytest.fixture
    def populated(self, mlpub_pg):
        for n in range(60):
            add_event(
                mlpub_pg,
                f"MLA{n % 6}",
                "status_paused" if n % 2 else "status_activated",
                day(n),
                store=57997 if n % 3 else 2645,
            )
        with mlpub_pg.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("ANALYZE ml_item_events"))
        return mlpub_pg

    def plan(self, db, statement) -> str:
        db.execute(text("SET LOCAL enable_seqscan = off"))
        return "\n".join(row[0] for row in db.execute(text("EXPLAIN " + statement.sql), statement.params))

    def test_item_timeline_uses_the_item_index(self, populated, db) -> None:
        plan = self.plan(db, events_query.item_timeline_statement("MLA1", cursor=Cursor(day(3), 1), limit=10))
        assert "ix_ml_item_events_item" in plan

    def test_type_and_range_uses_the_type_index(self, populated, db) -> None:
        statement = events_query.search_statement(event_type="status_paused", since=day(2), until=day(40), limit=10)
        assert "ix_ml_item_events_type" in self.plan(db, statement)

    def test_store_and_type_uses_the_store_index(self, populated, db) -> None:
        statement = events_query.search_statement(
            event_type="status_paused", official_store_id=57997, since=day(2), until=day(40), limit=10
        )
        assert "ix_ml_item_events_store" in self.plan(db, statement)
