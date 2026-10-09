"""P8b.T1: `GET /api/ml-publications/view/items/{item_id}/events` and `/history`, the Eventos and Historial tabs.

Same harness as the detail and variations tests (permissions in the SQLite test database, the store in a throwaway
Postgres schema built from the real migrations). Every change-log row is the real diff between a captured body and a
copy of it with named fields changed, with the context the store writes; every event is what `derive_events` makes of
that row, so the rows are the ones the store would have left, not shapes made up for the test.
"""

# ruff: noqa: F811 -- the fixtures are imported from the list's test modules and used by name

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Optional

import pytest
from sqlalchemy import event, text

from app.routers import ml_publications_view
from app.services.ml_publications import settings_store
from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.events import ChangeRow, EVENT_TYPES, dedupe_key, derive_events
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.store import item_context
from app.services.ml_publications.subresource_context import entries_context
from app.services.ml_publications.view import events_view, history
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_markup import pg, reader, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import (  # noqa: F401
    bulk_item,
    mlpub_pg,
    sample_item,
    subresource_body,
)
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications/view/items"
ITEM = "MLA874027718"  # active, store item of the captures; its user product and family are the captured ones
OTHER = "MLA935110613"  # another captured item, another user product and family
USER_PRODUCT, FAMILY = "MLAU245334053", 5385385211222674
OTHER_USER_PRODUCT, OTHER_FAMILY = "MLAU282291766", 7695306917964170


def events_url(item_id: str = ITEM) -> str:
    return f"{BASE}/{item_id}/events"


def history_url(item_id: str = ITEM) -> str:
    return f"{BASE}/{item_id}/history"


def events_of(client, headers, item_id: str = ITEM, **params):
    return client.get(events_url(item_id), headers=headers, params=params)


def history_of(client, headers, item_id: str = ITEM, **params):
    return client.get(history_url(item_id), headers=headers, params=params)


def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


# --- rows: a real diff, its context, and the events the rules derive from it ------------------------------------


def log_change(
    conn,
    resource: str,
    old: Any,
    new: Any,
    *,
    entity_id: str,
    item_id: Optional[str],
    at: datetime,
    kind: str = "change",
    context: Optional[dict] = None,
    with_events: bool = False,
) -> int:
    """One `ml_change_log` row for old -> new (the reportable changes), and with `with_events` its derived events."""
    spec = RESOURCES[resource]
    reportable, _ = split_excluded(diff(old, new, spec), resource)
    changes = [c.as_dict() for c in reportable]
    if context is None:
        context = item_context(spec.mapper(old), spec.mapper(new), None) if resource == "item" else {}
        context = {**context, **entries_context(resource, old, new)} if resource != "item" else context
    log_id = insert_log(conn, resource, entity_id, item_id, at, kind, changes, context)
    if with_events:
        row = ChangeRow(log_id, resource, item_id, kind, at, None, changes, context)
        for derived in derive_events(row):
            insert_event(conn, log_id, derived, at)
    return log_id


def insert_log(conn, resource, entity_id, item_id, at, kind, changes, context) -> int:
    return conn.execute(
        text(
            "INSERT INTO ml_change_log (resource_type, entity_id, item_id, kind, observed_at, changed_paths, changes, "
            "context) VALUES (:r, :e, :i, :k, :at, CAST(:paths AS text[]), CAST(:changes AS jsonb), "
            "CAST(:context AS jsonb)) RETURNING id"
        ),
        {
            "r": resource,
            "e": entity_id,
            "i": item_id,
            "k": kind,
            "at": at,
            "paths": [c["p"] for c in changes],
            "changes": json.dumps(changes),
            "context": json.dumps(context),
        },
    ).scalar_one()


def insert_event(conn, log_id: int, derived, at: datetime) -> int:
    key = dedupe_key(log_id, derived.event_type, derived.promotion_key, derived.price_kind)
    return conn.execute(
        text(
            "INSERT INTO ml_item_events (event_type, item_id, promotion_id, promotion_type, price_kind, old_value, "
            "new_value, payload, observed_at, change_log_id, dedupe_key) VALUES (:t, :i, :pid, :ptype, :kind, "
            "CAST(:old AS jsonb), CAST(:new AS jsonb), CAST(:payload AS jsonb), :at, :log, :key) RETURNING id"
        ),
        {
            "t": derived.event_type,
            "i": derived.item_id,
            "pid": derived.promotion_id,
            "ptype": derived.promotion_type,
            "kind": derived.price_kind,
            "old": json.dumps(derived.old_value),
            "new": json.dumps(derived.new_value),
            "payload": json.dumps(derived.payload),
            "at": at,
            "log": log_id,
            "key": key,
        },
    ).scalar_one()


def mutated(body: dict, **fields: Any) -> dict:
    out = copy.deepcopy(body)
    out.update(fields)
    return out


def paused(at: datetime, conn, item: str = ITEM, **extra) -> int:
    """The captured active item paused (status_paused event), `extra` fields changed with it."""
    old = sample_item(ITEM)
    new = mutated(old, status="paused", sub_status=["out_of_stock"], available_quantity=0, **extra)
    return log_change(conn, "item", old, new, entity_id=item, item_id=item, at=at, with_events=True)


def priced(at: datetime, conn, amount: float = 60000.0, item: str = ITEM) -> int:
    """The captured standard price with its amount changed (price_changed event)."""
    old = subresource_body("prices", "prices_MLA874027718")
    new = copy.deepcopy(old)
    new["prices"][0]["amount"] = amount
    return log_change(conn, "prices", old, new, entity_id=item, item_id=item, at=at, with_events=True)


def fill(conn) -> None:
    seed.add_item(conn, ITEM, title="Combo", user_product_id=USER_PRODUCT, family_id=FAMILY, http_status=200)
    seed.add_item(conn, OTHER, title="Otro", user_product_id=OTHER_USER_PRODUCT, family_id=OTHER_FAMILY)


@pytest.fixture()
def rows(pg):
    seed_rows(pg, fill)


@pytest.fixture()
def events_on(rows):
    settings_store.set_setting("events.enabled", True, "test")


class TestErrors:
    @pytest.mark.parametrize("url", [events_url, history_url])
    def test_unknown_item_is_404(self, client, rows, reader, url) -> None:
        response = client.get(url("MLA404"), headers=reader)
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.parametrize("url", [events_url, history_url])
    def test_an_id_that_ml_says_never_existed_is_404(self, client, pg, reader, url) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA77", never_existed=True))
        assert client.get(url("MLA77"), headers=reader).status_code == 404

    @pytest.mark.parametrize("url", [events_url, history_url])
    @pytest.mark.parametrize("item_id", ["mla10", "MLA", "10", "MLA1x"])
    def test_a_malformed_id_is_422(self, client, rows, reader, url, item_id) -> None:
        assert client.get(url(item_id), headers=reader).status_code == 422

    @pytest.mark.parametrize("url", [events_url, history_url])
    def test_without_ml_ops_ver_it_is_403(self, client, rows, auth_headers, url) -> None:
        response = client.get(url(), headers=auth_headers)
        assert response.status_code == 403 and "ml_ops.ver" in response.json()["error"]["message"]

    @pytest.mark.parametrize("url", [events_url, history_url])
    def test_authentication_is_required(self, client, rows, url) -> None:
        assert client.get(url()).status_code in (401, 403)

    @pytest.mark.parametrize("name, value", [("limit", 0), ("limit", 101), ("limit", "x"), ("cursor", "nonsense")])
    def test_a_bad_events_parameter_is_422_naming_it(self, client, events_on, reader, name, value) -> None:
        response = events_of(client, reader, **{name: value})
        assert response.status_code == 422
        if name == "cursor":
            assert response.json()["error"]["field"] == "cursor"

    @pytest.mark.parametrize("name, value", [("limit", 0), ("limit", 51), ("cursor", "nonsense")])
    def test_a_bad_history_parameter_is_422(self, client, rows, reader, name, value) -> None:
        assert history_of(client, reader, **{name: value}).status_code == 422

    def test_both_routes_only_read(self) -> None:
        verbs = {
            m
            for route in ml_publications_view.router.routes
            if route.path.endswith(("/events", "/history"))
            for m in route.methods
        }
        assert verbs == {"GET"}


class TestEvents:
    def test_disabled_flag_answers_an_empty_list_even_with_events_stored(self, client, rows, pg, reader) -> None:
        """S55.4: the events exist, the flag is off: nothing is invented and nothing is shown."""
        with pg.begin() as conn:
            paused(seed.hours_ago(1), conn)
        assert ok(events_of(client, reader)) == {"enabled": False, "events": [], "next_cursor": None}

    def test_newest_first_with_the_stored_fields_and_a_spanish_label(self, client, events_on, pg, reader) -> None:
        with pg.begin() as conn:
            paused(seed.hours_ago(5), conn)
            priced(seed.hours_ago(2), conn)
        body = ok(events_of(client, reader))
        assert body["enabled"] is True and body["next_cursor"] is None
        # the pause row also depletes the stock (available_quantity 2 -> 0): its events share the row's instant
        assert body["events"][0]["event_type"] == "price_changed"
        newest = body["events"][0]
        oldest = next(e for e in body["events"] if e["event_type"] == "status_paused")
        assert {e["event_type"] for e in body["events"][1:]} == {"status_paused", "stock_depleted"}
        assert newest["label"] == "Cambio de precio" and oldest["label"] == events_view.label_of("status_paused")
        assert (oldest["old_value"], oldest["new_value"]) == ("active", "paused")
        assert newest["price_kind"] == "standard" and newest["promotion_type"] is None
        assert set(newest) == {
            "id",
            "event_type",
            "label",
            "observed_at",
            "promotion_type",
            "price_kind",
            "old_value",
            "new_value",
        }

    def test_an_unmapped_type_has_the_generic_spanish_label(self, client, events_on, pg, reader) -> None:
        def odd(conn) -> None:
            seed.add_event(conn, ITEM, "something_new", seed.hours_ago(1))

        seed_rows(pg, odd)
        (event_,) = ok(events_of(client, reader))["events"]
        assert event_["event_type"] == "something_new" and event_["label"] == "Evento"

    def test_only_the_events_of_the_item(self, client, events_on, pg, reader) -> None:
        with pg.begin() as conn:
            paused(seed.hours_ago(3), conn)
            old = bulk_item(OTHER)
            log_change(
                conn,
                "item",
                old,
                mutated(old, status="active"),
                entity_id=OTHER,
                item_id=OTHER,
                at=seed.hours_ago(1),
                with_events=True,
            )
        assert {e["event_type"] for e in ok(events_of(client, reader))["events"]} == {"status_paused", "stock_depleted"}
        assert [e["event_type"] for e in ok(events_of(client, reader, OTHER))["events"]] == ["status_activated"]

    def test_an_item_without_events_has_an_empty_list_not_an_error(self, client, events_on, reader) -> None:
        assert ok(events_of(client, reader)) == {"enabled": True, "events": [], "next_cursor": None}

    def test_the_cursor_walks_the_whole_history_without_repeats_or_skips(self, client, events_on, pg, reader) -> None:
        """S57.1: 7 events, three of them at the same instant, pages of 3."""
        same = seed.hours_ago(4)

        def many(conn) -> None:
            for n in range(1, 5):
                seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(10 + n))
            for _ in range(3):
                seed.add_event(conn, ITEM, "status_paused", same)

        seed_rows(pg, many)
        every = []
        cursor = None
        for _ in range(5):
            params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
            body = ok(events_of(client, reader, **params))
            every += body["events"]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(every) == 7 and len({e["id"] for e in every}) == 7
        keys = [(e["observed_at"], e["id"]) for e in every]
        assert keys == sorted(keys, reverse=True)

    def test_the_last_page_has_no_cursor_and_a_full_one_does(self, client, events_on, pg, reader) -> None:
        def two(conn) -> None:
            seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(2))
            seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(1))

        seed_rows(pg, two)
        assert ok(events_of(client, reader, limit=2))["next_cursor"] is None
        assert ok(events_of(client, reader, limit=1))["next_cursor"] is not None

    def test_the_default_page_is_50_and_the_events_table_is_all_it_reads(self, client, events_on, pg, reader) -> None:
        """S55.3: no sale or derived event exists here: the only store table read for the events is `ml_item_events`."""

        def sixty(conn) -> None:
            for n in range(60):
                seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(n + 1))

        seed_rows(pg, sixty)
        statements = record(pg, lambda: ok(events_of(client, reader)))
        assert len(ok(events_of(client, reader))["events"]) == events_view.DEFAULT_LIMIT == 50
        tables = {t for s in statements for t in ("ml_item_events", "ml_change_log", "ml_items") if t in s}
        assert tables == {"ml_item_events", "ml_items"}  # the item's existence, then its events; no sales, no log

    def test_the_statement_count_does_not_depend_on_the_page(self, client, events_on, pg, reader) -> None:
        def n_events(n: int):
            def run(conn) -> None:
                for k in range(n):
                    seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(k + 1))

            return run

        seed_rows(pg, n_events(3))
        small = record(pg, lambda: ok(events_of(client, reader)))
        seed_rows(pg, n_events(40))
        large = record(pg, lambda: ok(events_of(client, reader)))
        assert len(small) == len(large) <= 4

    def test_the_read_is_bounded_in_time_before_the_events_are_read(self, client, events_on, pg, reader) -> None:
        statements = record(pg, lambda: ok(events_of(client, reader)))
        bound = next(i for i, s in enumerate(statements) if "SET LOCAL statement_timeout" in s)
        read = next(i for i, s in enumerate(statements) if "FROM ml_item_events" in s)
        assert bound < read and events_view.STATEMENT_TIMEOUT == "3s"

    def test_a_slow_query_is_a_controlled_503(self, client, events_on, pg, reader, monkeypatch) -> None:
        real = events_view.events_query.item_timeline_statement

        def slow(*args, **kwargs):
            statement = real(*args, **kwargs)
            return type(statement)(statement.sql.replace("SELECT ", "SELECT pg_sleep(1), ", 1), statement.params)

        seed_rows(pg, lambda conn: seed.add_event(conn, ITEM, "price_changed", seed.hours_ago(1)))  # pg_sleep per row
        monkeypatch.setattr(events_view, "STATEMENT_TIMEOUT", "100ms")
        monkeypatch.setattr(events_view.events_query, "item_timeline_statement", slow)
        response = events_of(client, reader)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"

    def test_every_event_type_the_rules_emit_is_labelled_in_the_response(self, client, events_on, pg, reader) -> None:
        def every_type(conn) -> None:
            for n, event_type in enumerate(EVENT_TYPES):
                seed.add_event(conn, ITEM, event_type, seed.hours_ago(n + 1))

        seed_rows(pg, every_type)
        listed = ok(events_of(client, reader, limit=100))["events"]
        assert {e["event_type"] for e in listed} == set(EVENT_TYPES)
        assert all(e["label"] != "Evento" for e in listed)


class TestHistory:
    def test_empty(self, client, rows, reader) -> None:
        """S58.2."""
        assert ok(history_of(client, reader)) == {"entries": [], "next_cursor": None}

    def test_the_history_does_not_need_the_events_flag(self, client, rows, pg, reader) -> None:
        with pg.begin() as conn:
            paused(seed.hours_ago(1), conn)
        assert len(ok(history_of(client, reader))["entries"]) == 1

    def test_price_is_business_and_a_technical_path_waits_apart(self, client, rows, pg, reader) -> None:
        """S58.1: a price change and a technical-path change in one row."""
        with pg.begin() as conn:
            old = sample_item(ITEM)
            new = mutated(old, price=old["price"] + 500, health=0.1)
            log_change(conn, "item", old, new, entity_id=ITEM, item_id=ITEM, at=seed.hours_ago(1))
        (entry,) = ok(history_of(client, reader))["entries"]
        assert entry["resource_type"] == "item" and entry["kind"] == "change"
        assert [c["path"] for c in entry["business"]] == ["price"]
        assert [c["path"] for c in entry["technical"]] == ["health"]
        (price,) = entry["business"]
        assert (price["old"], price["new"]) == (55882.0, 56382.0)
        assert price["label_key"] == "price" and price["label"] == "Precio"
        assert entry["technical"][0]["label_key"] is None

    def test_one_change_touching_several_fields_is_one_line_per_field(self, client, rows, pg, reader) -> None:
        """S58.3."""
        with pg.begin() as conn:
            paused(seed.hours_ago(1), conn, title="Otro titulo")
        (entry,) = ok(history_of(client, reader))["entries"]
        lines = {c["path"]: (c["old"], c["new"]) for c in entry["business"]}
        assert lines["status"] == ("active", "paused") and lines["available_quantity"][1] == 0
        assert lines["title"][1] == "Otro titulo" and lines["sub_status[=out_of_stock]"] == (None, "out_of_stock")
        assert len(entry["business"]) == len(lines)

    def test_item_rows_and_the_rows_of_its_user_product_and_family_merge_newest_first(
        self, client, rows, pg, reader
    ) -> None:
        with pg.begin() as conn:
            paused(seed.hours_ago(6), conn)
            priced(seed.hours_ago(4), conn)
            stock = subresource_body("stock", "user_product_stock_MLAU245334053")
            moved = copy.deepcopy(stock)
            moved["locations"][1]["quantity"] = 7
            log_change(
                conn, "stock", stock, moved, entity_id=USER_PRODUCT, item_id=None, at=seed.hours_ago(5), context={}
            )
            family = subresource_body("family", "family_5385385211222674")
            grown = mutated(family, user_products_ids=[*family["user_products_ids"], "MLAU1"])
            log_change(
                conn, "family", family, grown, entity_id=str(FAMILY), item_id=None, at=seed.hours_ago(3), context={}
            )
        entries = ok(history_of(client, reader))["entries"]
        assert [e["resource_type"] for e in entries] == ["family", "prices", "stock", "item"]
        by_type = {e["resource_type"]: e for e in entries}
        assert [c["path"] for c in by_type["stock"]["business"]] == ["locations[meli_facility].quantity"]
        assert by_type["family"]["business"] == [] and by_type["family"]["technical"]

    def test_nothing_of_another_item_or_another_user_product_or_family(self, client, rows, pg, reader) -> None:
        with pg.begin() as conn:
            old = bulk_item(OTHER)
            log_change(conn, "item", old, mutated(old, price=1.0), entity_id=OTHER, item_id=OTHER, at=seed.hours_ago(1))
            stock = subresource_body("stock", "user_product_stock_MLAU266459622")
            moved = copy.deepcopy(stock)
            moved["locations"][0]["quantity"] = 1
            log_change(
                conn,
                "stock",
                stock,
                moved,
                entity_id=OTHER_USER_PRODUCT,
                item_id=None,
                at=seed.hours_ago(2),
                context={},
            )
            family = subresource_body("family", "family_994279717105509")
            log_change(
                conn,
                "family",
                family,
                mutated(family, user_products_ids=[]),
                entity_id=str(OTHER_FAMILY),
                item_id=None,
                at=seed.hours_ago(3),
                context={},
            )
        assert ok(history_of(client, reader))["entries"] == []

    def test_a_row_reachable_by_two_branches_is_listed_once(self, client, rows, pg, reader) -> None:
        """A user product row that also carries the item's id (the store does not write it so) is not read twice."""
        with pg.begin() as conn:
            insert_log(conn, "stock", USER_PRODUCT, ITEM, seed.hours_ago(1), "change", [{"p": "x", "op": "add"}], {})
        entries = ok(history_of(client, reader))["entries"]
        assert [e["resource_type"] for e in entries] == ["stock"]

    def test_a_row_that_says_the_item_is_gone_is_an_entry_even_without_changes(self, client, rows, pg, reader) -> None:
        with pg.begin() as conn:
            insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(1), "gone", [], {"status_old": "active"})
        (entry,) = ok(history_of(client, reader))["entries"]
        assert entry["kind"] == "gone" and entry["business"] == [] and entry["technical"] == []

    def test_equal_instants_are_ordered_by_id_descending_and_pages_never_repeat(self, client, rows, pg, reader) -> None:
        same = seed.hours_ago(2)
        ids: list[int] = []
        with pg.begin() as conn:
            for n in range(3):  # three item rows at one instant
                ids.append(insert_log(conn, "item", ITEM, ITEM, same, "change", [{"p": "title", "op": "replace"}], {}))
            for n in range(2):  # and two user product rows at that same instant
                ids.append(insert_log(conn, "stock", USER_PRODUCT, None, same, "change", [{"p": "x", "op": "add"}], {}))
            ids.append(insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(9), "change", [], {}))
        seen: list[int] = []
        cursor = None
        for _ in range(6):
            body = ok(history_of(client, reader, limit=2, **({"cursor": cursor} if cursor else {})))
            seen += [e["id"] for e in body["entries"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == [*sorted(ids[:5], reverse=True), ids[5]]  # same instant by id, then the older row

    def test_the_default_page_is_20_and_the_max_is_50(self, client, rows, pg, reader) -> None:
        def many(conn) -> None:
            for n in range(60):
                insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(n + 1), "change", [], {})

        seed_rows(pg, many)
        first = ok(history_of(client, reader))
        assert len(first["entries"]) == history.DEFAULT_LIMIT == 20 and first["next_cursor"]
        assert len(ok(history_of(client, reader, limit=50))["entries"]) == history.MAX_LIMIT == 50

    def test_the_statement_count_does_not_depend_on_the_page(self, client, rows, pg, reader) -> None:
        def n_rows(n: int):
            def run(conn) -> None:
                for k in range(n):
                    insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(k + 1), "change", [], {})

            return run

        seed_rows(pg, n_rows(2))
        small = record(pg, lambda: ok(history_of(client, reader)))
        seed_rows(pg, n_rows(45))
        large = record(pg, lambda: ok(history_of(client, reader)))
        assert len(small) == len(large) <= 4

    def test_the_read_is_bounded_in_time_and_uses_the_log_indexes(self, client, rows, pg, reader) -> None:
        statements = record(pg, lambda: ok(history_of(client, reader)))
        bound = next(i for i, s in enumerate(statements) if "SET LOCAL statement_timeout" in s)
        read = next(i for i, s in enumerate(statements) if "FROM ml_change_log" in s)
        assert bound < read and history.STATEMENT_TIMEOUT == "3s"
        assert sum("FROM ml_change_log" in s for s in statements) == 1  # the item's rows and the entities' in one

    def test_the_item_branch_is_an_index_scan_on_the_item_index(self, client, rows, pg, reader) -> None:
        with pg.begin() as conn:
            for k in range(30):
                insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(k + 1), "change", [], {})
            conn.execute(text("ANALYZE ml_change_log"))
        with pg.connect() as conn:
            conn.execute(text("SET enable_seqscan = off"))
            plan = "\n".join(
                row[0]
                for row in conn.execute(
                    text("EXPLAIN " + history.page_sql()),
                    {"item_id": ITEM, "user_product_id": USER_PRODUCT, "family_id": str(FAMILY), "row_limit": 21},
                )
            )
        assert "ix_ml_change_log_item" in plan and "ix_ml_change_log_entity" in plan

    def test_a_slow_query_is_a_controlled_503(self, client, rows, pg, reader, monkeypatch) -> None:
        seed_rows(pg, lambda conn: insert_log(conn, "item", ITEM, ITEM, seed.hours_ago(1), "change", [], {}))
        monkeypatch.setattr(history, "STATEMENT_TIMEOUT", "100ms")
        monkeypatch.setattr(
            history, "page_sql", lambda after=False: history.PAGE_SQL.replace("SELECT ", "SELECT pg_sleep(1), ", 1)
        )
        response = history_of(client, reader)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"


def record(pg, run) -> list[str]:
    """The SQL statements `run` sends to the store."""
    recorded: list[str] = []

    def listener(conn, cursor, statement, *rest) -> None:
        recorded.append(statement)

    event.listen(pg, "before_cursor_execute", listener)
    try:
        run()
    finally:
        event.remove(pg, "before_cursor_execute", listener)
    return recorded
