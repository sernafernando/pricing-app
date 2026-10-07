"""`subresource_store.apply_subresource`: the transactional upsert of one fetched sub-resource.

Postgres only (row locks, jsonb). Every payload is a real capture of `/items/{id}/description`,
`/prices` or `/sale_price`; a transition is a deep copy of a real body with the named field changed.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.settings_store import set_setting
from app.services.ml_publications.store import ApplyCounters, apply_fetch
from app.services.ml_publications.subresource_store import apply_subresource
from tests.services.ml_publications.conftest import sample_item, subresource_body, subresource_call

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 10, 6, 13, 0, 0, tzinfo=timezone.utc)
ACTIVE = "MLA874027718"  # active item of store 57997, brand Marvo (items sample); has prices/sale_price/description
TABLES = {"description": "ml_item_descriptions", "prices": "ml_item_prices", "sale_price": "ml_item_sale_prices"}


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def response(resource: str, body, minutes: float = 0, status: int = 200) -> MlResponse:
    received = at(minutes)
    return MlResponse(
        endpoint=resource,
        status=status,
        body=body,
        headers={},
        request_started_at=received - timedelta(seconds=1),
        received_at=received,
    )


def apply(resource: str, item_id: str, body, minutes: float = 0, status: int = 200, **kwargs):
    return apply_subresource(RESOURCES[resource], (item_id,), response(resource, body, minutes, status), **kwargs)


def row_of(engine, resource: str, item_id: str = ACTIVE):
    with engine.connect() as conn:
        return (
            conn.execute(text(f"SELECT * FROM {TABLES[resource]} WHERE item_id = :i"), {"i": item_id})
            .mappings()
            .first()
        )


def logs(engine, resource: str | None = None):
    sql = "SELECT * FROM ml_change_log" + (" WHERE resource_type = :r" if resource else "") + " ORDER BY id"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"r": resource} if resource else {}).mappings().all()


def events(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM ml_item_events ORDER BY id")).mappings().all()


def prices_body() -> dict:
    return subresource_body("prices", "prices_MLA874027718")


def sale_body() -> dict:
    return subresource_body("sale_price", "sale_price_MLA874027718")


def with_marketplace_amount(body: dict, amount: float) -> dict:
    out = copy.deepcopy(body)
    out["prices"][0]["amount"] = amount  # entry 465, the marketplace standard price
    return out


class TestFirstSighting:
    def test_writes_raw_typed_columns_and_hash_without_log_or_event(self, mlpub_pg) -> None:
        body = prices_body()
        outcome = apply("prices", ACTIVE, body, minutes=1)

        row = row_of(mlpub_pg, "prices")
        assert outcome.kind == "first_seen" and outcome.change_log_id is None and outcome.events == 0
        assert row["raw"] == body
        assert bytes(row["raw_hash"]) == canonical_hash(body, RESOURCES["prices"])
        assert (row["standard_amount"], row["currency_id"], row["active_promotion_amount"]) == (55882, "ARS", None)
        assert row["http_status"] == 200 and row["never_existed"] is False and row["gone_at"] is None
        assert row["fetched_at"] == at(1) and row["last_checked_at"] == at(1)
        assert logs(mlpub_pg) == []

    def test_every_fetched_resource_has_its_own_table(self, mlpub_pg) -> None:
        apply("description", ACTIVE, subresource_body("description", "description_MLA874027718"), minutes=1)
        apply("sale_price", ACTIVE, sale_body(), minutes=1)

        assert row_of(mlpub_pg, "description")["plain_text_length"] > 0
        assert row_of(mlpub_pg, "sale_price")["price_id"] == "465"


class TestUnchanged:
    def test_an_identical_body_only_moves_the_freshness_timestamps(self, mlpub_pg) -> None:
        apply("prices", ACTIVE, prices_body(), minutes=1)
        outcome = apply("prices", ACTIVE, prices_body(), minutes=5)

        row = row_of(mlpub_pg, "prices")
        assert outcome.kind == "unchanged"
        assert row["fetched_at"] == at(1) and row["last_checked_at"] == at(5)
        assert logs(mlpub_pg) == []


class TestChange:
    def test_a_real_change_writes_state_and_one_change_log_row_with_the_entries_context(self, mlpub_pg) -> None:
        """Real two-channel prices capture with the marketplace standard amount 55882.0 -> 60000.0."""
        old = prices_body()
        new = with_marketplace_amount(old, 60000.0)
        apply("prices", ACTIVE, old, minutes=1)
        outcome = apply("prices", ACTIVE, new, minutes=2)

        (entry,) = logs(mlpub_pg, "prices")
        assert outcome.kind == "changed" and outcome.change_log_id == entry["id"]
        assert entry["entity_id"] == ACTIVE and entry["item_id"] == ACTIVE and entry["kind"] == "change"
        assert entry["changed_paths"] == ["prices[465].amount"]
        assert entry["context"]["entries"]["old"]["standard"]["amount"] == "55882.0"
        assert entry["context"]["entries"]["new"]["standard"]["amount"] == "60000.0"
        row = row_of(mlpub_pg, "prices")
        assert row["raw"] == new and row["standard_amount"] == 60000 and row["fetched_at"] == at(2)

    def test_no_event_is_written_while_the_events_flag_is_off(self, mlpub_pg) -> None:
        old = prices_body()
        apply("prices", ACTIVE, old, minutes=1)
        outcome = apply("prices", ACTIVE, with_marketplace_amount(old, 60000.0), minutes=2)

        assert outcome.events == 0 and events(mlpub_pg) == []

    def test_with_events_on_the_price_event_carries_the_item_attribution(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        apply_fetch(RESOURCES["item"], (ACTIVE,), response("item", sample_item(ACTIVE), minutes=0))
        old = prices_body()
        apply("prices", ACTIVE, old, minutes=1)
        outcome = apply("prices", ACTIVE, with_marketplace_amount(old, 60000.0), minutes=2)

        (event,) = events(mlpub_pg)
        assert outcome.events == 1
        assert (event["event_type"], event["price_kind"], event["item_id"]) == ("price_changed", "standard", ACTIVE)
        assert (event["old_value"], event["new_value"]) == ("55882.0", "60000.0")
        assert (event["official_store_id"], event["brand"]) == (57997, "Marvo")
        assert event["change_log_id"] == outcome.change_log_id

    def test_flip_a_b_a_writes_two_change_rows_and_two_events(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        a = prices_body()
        b = with_marketplace_amount(a, 60000.0)
        apply("prices", ACTIVE, a, minutes=1)
        apply("prices", ACTIVE, b, minutes=2)
        apply("prices", ACTIVE, a, minutes=3)

        assert len(logs(mlpub_pg, "prices")) == 2
        assert [(e["old_value"], e["new_value"]) for e in events(mlpub_pg)] == [
            ("55882.0", "60000.0"),
            ("60000.0", "55882.0"),
        ]

    def test_the_event_flag_passed_by_the_caller_is_honoured(self, mlpub_pg) -> None:
        old = prices_body()
        apply("prices", ACTIVE, old, minutes=1)
        outcome = apply("prices", ACTIVE, with_marketplace_amount(old, 60000.0), minutes=2, events_enabled=True)
        assert outcome.events == 1


class TestSalePriceReferenceDate:
    def test_a_fetch_that_only_moves_reference_date_refreshes_raw_but_logs_nothing(self, mlpub_pg) -> None:
        """Real sale_price capture with exactly one field changed: `reference_date` (response time)."""
        set_setting("events.enabled", True, "test")
        old = sale_body()
        new = copy.deepcopy(old)
        new["reference_date"] = "2026-10-06T14:00:00Z"
        counters = ApplyCounters()
        apply("sale_price", ACTIVE, old, minutes=1, counters=counters)

        outcome = apply("sale_price", ACTIVE, new, minutes=2, counters=counters)

        row = row_of(mlpub_pg, "sale_price")
        assert outcome.kind == "noise_only" and outcome.change_log_id is None
        assert logs(mlpub_pg) == [] and events(mlpub_pg) == []
        assert row["raw"]["reference_date"] == "2026-10-06T14:00:00Z"
        assert bytes(row["raw_hash"]) == canonical_hash(new, RESOURCES["sale_price"])
        assert row["fetched_at"] == at(2)
        assert counters.noise_suppressed[("sale_price", "reference_date")] == 1

    def test_a_real_amount_change_is_logged_without_the_reference_date_path(self, mlpub_pg) -> None:
        old = sale_body()
        new = copy.deepcopy(old)
        new.update(amount=50000.0, reference_date="2026-10-06T14:00:00Z")
        apply("sale_price", ACTIVE, old, minutes=1)
        apply("sale_price", ACTIVE, new, minutes=2)

        (entry,) = logs(mlpub_pg, "sale_price")
        assert entry["changed_paths"] == ["amount"]


class TestNotFound:
    def test_a_first_404_is_recorded_as_never_existed_without_a_log(self, mlpub_pg) -> None:
        call = subresource_call("description", "description_unknown")
        outcome = apply("description", "MLA1", call["body"], status=404, minutes=1)

        row = row_of(mlpub_pg, "description", "MLA1")
        assert outcome.kind == "never_existed"
        assert row["raw"] is None and row["never_existed"] is True and row["http_status"] == 404
        assert row["error_body"] == call["body"] and row["gone_at"] is not None
        assert logs(mlpub_pg) == []

    def test_a_404_after_a_stored_body_marks_gone_once_and_keeps_the_last_raw(self, mlpub_pg) -> None:
        body = subresource_body("description", "description_MLA874027718")
        missing = subresource_call("description", "description_unknown")["body"]
        apply("description", ACTIVE, body, minutes=1)

        first = apply("description", ACTIVE, missing, status=404, minutes=2)
        second = apply("description", ACTIVE, missing, status=404, minutes=3)

        row = row_of(mlpub_pg, "description")
        (entry,) = logs(mlpub_pg, "description")
        assert first.kind == "gone" and entry["kind"] == "gone" and second.kind == "unchanged"
        assert row["raw"] == body and row["gone_at"] == at(2) and row["http_status"] == 404

    def test_a_200_after_gone_is_a_restore_and_clears_the_gone_marker(self, mlpub_pg) -> None:
        body = subresource_body("description", "description_MLA874027718")
        missing = subresource_call("description", "description_unknown")["body"]
        apply("description", ACTIVE, body, minutes=1)
        apply("description", ACTIVE, missing, status=404, minutes=2)

        outcome = apply("description", ACTIVE, body, minutes=3)

        row = row_of(mlpub_pg, "description")
        assert outcome.kind == "restored" and row["gone_at"] is None and row["http_status"] == 200
        assert [e["kind"] for e in logs(mlpub_pg, "description")] == ["gone", "restored"]

    def test_a_gone_prices_row_yields_no_price_event(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        apply("prices", ACTIVE, prices_body(), minutes=1)
        missing = subresource_call("prices", "prices_unknown")["body"]
        outcome = apply("prices", ACTIVE, missing, status=404, minutes=2)

        assert outcome.kind == "gone" and outcome.events == 0 and events(mlpub_pg) == []


class TestErrors:
    @pytest.mark.parametrize("status", [403, 500])
    def test_a_non_2xx_is_recorded_with_its_status_and_body_and_keeps_the_state(self, mlpub_pg, status) -> None:
        """Synthetic transport fault (no 403/5xx was captured): the error body is a generic ML error."""
        body = prices_body()
        apply("prices", ACTIVE, body, minutes=1)
        error_body = {"message": "forbidden", "error": "forbidden", "status": status, "cause": []}

        outcome = apply("prices", ACTIVE, error_body, status=status, minutes=2)

        row = row_of(mlpub_pg, "prices")
        assert outcome.kind == "error_recorded"
        assert row["http_status"] == status and row["error_body"] == error_body
        assert row["last_error"] == f"HTTP {status}"
        assert row["raw"] == body and row["standard_amount"] == 55882 and row["gone_at"] is None
        assert logs(mlpub_pg) == []

    def test_a_malformed_2xx_is_an_error_not_a_state(self, mlpub_pg) -> None:
        body = subresource_body("description", "description_MLA874027718")
        apply("description", ACTIVE, body, minutes=1)

        outcome = apply("description", ACTIVE, {"unexpected": True}, minutes=2)

        row = row_of(mlpub_pg, "description")
        assert outcome.kind == "error_recorded"
        assert row["last_error"].startswith("malformed") and row["raw"] == body

    def test_a_success_after_an_error_clears_it(self, mlpub_pg) -> None:
        body = prices_body()
        apply("prices", ACTIVE, body, minutes=1)
        apply("prices", ACTIVE, {"error": "x"}, status=500, minutes=2)
        apply("prices", ACTIVE, body, minutes=3)

        row = row_of(mlpub_pg, "prices")
        assert (row["http_status"], row["error_body"], row["last_error"]) == (200, None, None)


class TestStaleResponses:
    def test_a_response_whose_request_started_before_the_stored_one_is_discarded(self, mlpub_pg) -> None:
        old = prices_body()
        counters = ApplyCounters()
        apply("prices", ACTIVE, old, minutes=10, counters=counters)

        outcome = apply(
            "prices", ACTIVE, with_marketplace_amount(old, 1.0), minutes=5, counters=counters, events_enabled=True
        )

        assert outcome.kind == "stale" and counters.stale_discarded == 1
        assert row_of(mlpub_pg, "prices")["raw"] == old
        assert logs(mlpub_pg) == []
