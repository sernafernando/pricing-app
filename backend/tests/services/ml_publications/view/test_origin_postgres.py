"""T3: every event and history entry of the Publicaciones ML panel says who caused it (`origin`, `informational`).

Same harness as `test_events_history_postgres.py` (the store in a throwaway Postgres schema, the endpoints through
the client), plus the audit tables with production's column types (`seed.AUDIT_DDL`). Events and change-log rows
are the captured production rows of MLA1402898289, stored on this test's item.
"""

# ruff: noqa: F811 -- the fixtures are imported from the list's test modules and used by name

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.ml_publications import settings_store
from app.services.ml_publications.view import origin
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_markup import pg, reader, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import load_fixture, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_events_history_postgres import (
    CAPTURE,
    ITEM,
    events_of,
    fill,
    history_of,
    insert_log,
    ok,
    record,
    store_captured_event,
)

pytestmark = pytest.mark.postgres

CAPTURED = load_fixture(CAPTURE)
EVENTS = {e["id"]: e for e in CAPTURED["events"]}
LOG = {row["id"]: row for row in CAPTURED["change_log"]}
AT = seed.hours_ago(2)


@pytest.fixture()
def audited(pg) -> int:
    """The items, the audit tables and one user; the user's id. The events flag is on."""
    with pg.begin() as conn:
        fill(conn)
        seed.create_audit_tables(conn)
        user_id = seed.add_user(conn, "Ana Pérez", "aperez")
    settings_store.set_setting("events.enabled", True, "test")
    return user_id


def by_type(body: dict) -> dict:
    return {e["event_type"]: e for e in body["events"]}


class TestEventsOrigin:
    def test_each_event_says_who_caused_it(self, client, audited, pg, reader) -> None:
        def rows(conn) -> None:
            store_captured_event(conn, EVENTS[3689], AT)  # promotion_activated C-MLA1717163
            store_captured_event(conn, EVENTS[6378], AT - timedelta(hours=1))  # promotion_offered
            store_captured_event(conn, EVENTS[42330], AT - timedelta(hours=2))  # status_paused
            seed.add_write_log(conn, ITEM, "enroll", "C-MLA1717163", AT - timedelta(minutes=4), audited)

        seed_rows(pg, rows)
        events = by_type(ok(events_of(client, reader)))
        activated, offered, paused = (events[t] for t in ("promotion_activated", "promotion_offered", "status_paused"))
        assert activated["origin"] == {"kind": "nosotros", "user_name": "Ana Pérez"}
        assert activated["informational"] is False
        assert offered["origin"] == {"kind": "ml", "user_name": None} and offered["informational"] is True
        assert paused["origin"] == {"kind": "sin_registrar", "user_name": None} and paused["informational"] is False

    def test_a_write_outside_the_window_or_of_another_item_is_not_ours(self, client, audited, pg, reader) -> None:
        def rows(conn) -> None:
            store_captured_event(conn, EVENTS[3689], AT)
            late = AT - origin.ORIGIN_WINDOW - timedelta(minutes=1)
            seed.add_write_log(conn, ITEM, "enroll", "C-MLA1717163", late, audited)
            seed.add_write_log(conn, "MLA935110613", "enroll", "C-MLA1717163", AT - timedelta(minutes=1), audited)

        seed_rows(pg, rows)
        (activated,) = ok(events_of(client, reader))["events"]
        assert activated["origin"] == {"kind": "sin_registrar", "user_name": None}

    def test_a_write_with_no_user_is_automatic(self, client, audited, pg, reader) -> None:
        def rows(conn) -> None:
            store_captured_event(conn, EVENTS[43804], AT)  # promotion_finished C-MLA1717163 (was started)
            seed.add_write_log(conn, ITEM, "remove", "C-MLA1717163", AT - timedelta(minutes=2), None)

        seed_rows(pg, rows)
        (finished,) = ok(events_of(client, reader))["events"]
        assert finished["origin"] == {"kind": "automatico", "user_name": None}

    def test_one_audit_read_whatever_the_page(self, client, audited, pg, reader) -> None:
        def n_activations(n: int):
            def run(conn) -> None:
                for k in range(n):
                    store_captured_event(conn, {**EVENTS[3689], "id": f"{n}-{k}"}, AT - timedelta(hours=k))

            return run

        seed_rows(pg, n_activations(2))
        small = record(pg, lambda: ok(events_of(client, reader)))
        seed_rows(pg, n_activations(30))
        large = record(pg, lambda: ok(events_of(client, reader)))
        # the flag, the time bound, the item, its events, the audit read, and (these are promotion events) the
        # promotion-name lookup of `events_view.promotion_names`, which only runs on a page with promotion events
        assert len(small) == len(large) <= 6
        for statements in (small, large):
            assert sum("FROM ml_write_log" in s for s in statements) == 1
            assert sum("ml_item_seller_promotions" in s for s in statements) == 1

    def test_events_that_cannot_be_ours_read_no_audit(self, client, audited, pg, reader) -> None:
        seed_rows(pg, lambda conn: store_captured_event(conn, EVENTS[6378], AT))
        statements = record(pg, lambda: ok(events_of(client, reader)))
        assert not any("ml_write_log" in s for s in statements)


class TestHistoryOrigin:
    def captured_row(self, conn, log_id: int, at) -> int:
        row = LOG[log_id]
        return insert_log(conn, row["resource_type"], ITEM, ITEM, at, row["kind"], row["changes"], {})

    def test_each_entry_says_who_caused_it(self, client, audited, pg, reader) -> None:
        def rows(conn) -> None:
            self.captured_row(conn, 7672, AT)  # promotions: C-MLA1717163 started
            self.captured_row(conn, 9282, AT - timedelta(hours=1))  # promotions: suggestions and candidates only
            self.captured_row(conn, 70046, AT - timedelta(hours=2))  # item price
            seed.add_write_log(conn, ITEM, "enroll", "C-MLA1717163", AT - timedelta(minutes=6), audited)

        seed_rows(pg, rows)
        started, offers, price = ok(history_of(client, reader))["entries"]
        assert started["origin"] == {"kind": "nosotros", "user_name": "Ana Pérez"} and not started["informational"]
        assert offers["origin"] == {"kind": "ml", "user_name": None} and offers["informational"] is True
        assert price["origin"] == {"kind": "sin_registrar", "user_name": None} and not price["informational"]

    def test_a_pxq_publish_in_auditoria_explains_a_prices_row(self, client, audited, pg, reader) -> None:
        def rows(conn) -> None:
            self.captured_row(conn, 7671, AT)
            values = {"mla": ITEM, "tier_id": 7, "cantidad_minima": 3, "precio_unitario": "70000", "accion": "create"}
            seed.add_auditoria(conn, "PXQ_PRECIO_PUBLICADO", values, AT - timedelta(minutes=3), audited)

        seed_rows(pg, rows)
        (entry,) = ok(history_of(client, reader))["entries"]
        assert entry["origin"] == {"kind": "nosotros", "user_name": "Ana Pérez"}

    def test_a_manual_link_is_ours_and_the_sku_rule_is_automatic(self, client, audited, pg, reader) -> None:
        """Production `product_link` rows (MLA3505165240:0, 2026-10-17): the changes and the context the store wrote."""
        changes = [
            {"p": "producto_item_id", "op": "replace", "new": None, "old": 318},
            {"p": "match_status", "op": "replace", "new": "unmatched", "old": "linked"},
            {"p": "matched_sku", "op": "replace", "new": "318", "old": "1210002615563"},
        ]
        context = {"linked_by": None, "source_new": "sku_auto", "source_old": "sku_auto", "variation_id": 0}

        def rows(conn) -> None:
            entity = f"{ITEM}:0"
            insert_log(conn, "product_link", entity, ITEM, AT, "change", changes, {**context, "source_new": "manual"})
            insert_log(conn, "product_link", entity, ITEM, AT - timedelta(hours=1), "change", changes, context)
            values = {"mla": ITEM, "variation_id": 0, "producto_item_id": None, "source": "manual_none"}
            seed.add_auditoria(conn, "ML_VINCULO_SIN_PRODUCTO", values, AT, audited)

        seed_rows(pg, rows)
        manual, rule = ok(history_of(client, reader))["entries"]
        assert manual["origin"] == {"kind": "nosotros", "user_name": "Ana Pérez"}
        assert rule["origin"] == {"kind": "automatico", "user_name": None}

    def test_ml_side_rows_are_ml_without_reading_the_audit(self, client, audited, pg, reader) -> None:
        seed_rows(pg, lambda conn: self.captured_row(conn, 34965, AT))  # visits
        statements = record(pg, lambda: ok(history_of(client, reader)))
        (visits,) = ok(history_of(client, reader))["entries"]
        assert visits["origin"] == {"kind": "ml", "user_name": None} and visits["informational"] is True
        assert not any("ml_write_log" in s for s in statements)

    def test_our_free_shipping_fix_is_automatic(self, client, audited, pg, reader) -> None:
        off = [{"p": "shipping.free_shipping", "op": "replace", "new": False, "old": True}]

        def rows(conn) -> None:
            insert_log(conn, "item", ITEM, ITEM, AT, "change", off, {})
            seed.add_free_shipping_fix(conn, ITEM, AT - timedelta(minutes=5))

        seed_rows(pg, rows)
        (entry,) = ok(history_of(client, reader, tecnicos="true"))["entries"]
        assert entry["origin"] == {"kind": "automatico", "user_name": None}

    def test_one_audit_read_whatever_the_page(self, client, audited, pg, reader) -> None:
        def n_rows(n: int):
            def run(conn) -> None:
                for k in range(n):
                    self.captured_row(conn, 7672, AT - timedelta(hours=k))

            return run

        seed_rows(pg, n_rows(2))
        small = record(pg, lambda: ok(history_of(client, reader)))
        seed_rows(pg, n_rows(40))
        large = record(pg, lambda: ok(history_of(client, reader)))
        assert len(small) == len(large) <= 4
        assert sum("FROM ml_write_log" in s for s in large) == 1
