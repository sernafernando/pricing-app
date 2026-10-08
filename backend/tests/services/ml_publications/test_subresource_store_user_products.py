"""`subresource_store.apply_subresource` for the resources keyed by something other than an item:
`user_product` and `stock` (keyed by user product id) and `family` (keyed by the BIGINT family id).

Postgres only. Every payload is a real capture of `/user-products/{id}`, `/user-products/{id}/stock` or
`/sites/MLA/user-products-families/{id}` (2026-10-06); a transition is a deep copy of a real body with the
named field changed. The 403 is a synthetic transport fault (no 403 was captured); the 404 body is the
generic ML not-found shape of the captured item sub-resources, labelled where used.
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
from app.services.ml_publications.subresource_store import apply_subresource
from tests.services.ml_publications.conftest import subresource_body

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 10, 6, 13, 0, 0, tzinfo=timezone.utc)
UP = "MLAU245334053"
FAMILY = "5385385211222674"
KEYS = {"user_product": "user_product_id", "stock": "user_product_id", "family": "family_id"}
TABLES = {"user_product": "ml_user_products", "stock": "ml_user_product_stock", "family": "ml_user_product_families"}
NOT_FOUND_BODY = {"message": "not found", "error": "not_found", "status": 404, "cause": []}  # synthetic 404 body


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


def apply(resource: str, key: str, body, minutes: float = 0, status: int = 200, **kwargs):
    return apply_subresource(RESOURCES[resource], (key,), response(resource, body, minutes, status), **kwargs)


def row_of(engine, resource: str, key: str):
    with engine.connect() as conn:
        return (
            conn.execute(text(f"SELECT * FROM {TABLES[resource]} WHERE {KEYS[resource]} = :k"), {"k": key})
            .mappings()
            .first()
        )


def logs(engine, resource: str | None = None):
    sql = "SELECT * FROM ml_change_log" + (" WHERE resource_type = :r" if resource else "") + " ORDER BY id"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"r": resource} if resource else {}).mappings().all()


def up_body() -> dict:
    return subresource_body("user_product", "user_product_MLAU245334053")


def stock_body() -> dict:
    return subresource_body("stock", "user_product_stock_MLAU245334053")


def family_body() -> dict:
    return subresource_body("family", "family_5385385211222674")


class TestFirstSighting:
    def test_a_user_product_keeps_raw_hash_and_the_exact_family_id(self, mlpub_pg) -> None:
        body = up_body()
        outcome = apply("user_product", UP, body, minutes=1)

        row = row_of(mlpub_pg, "user_product", UP)
        assert outcome.kind == "first_seen" and outcome.change_log_id is None and outcome.events == 0
        assert row["raw"] == body and bytes(row["raw_hash"]) == canonical_hash(body, RESOURCES["user_product"])
        assert row["family_id"] == 5385385211222674  # beyond 2**52: exact in the typed column
        assert (row["domain_id"], row["catalog_product_id"]) == ("MLA-PC_KEYBOARDS", "MLA15810042")
        assert row["http_status"] == 200 and row["fetched_at"] == at(1) and row["last_checked_at"] == at(1)
        assert logs(mlpub_pg) == []

    def test_the_stock_total_is_the_sum_of_its_locations(self, mlpub_pg) -> None:
        apply("stock", UP, stock_body(), minutes=1)
        other = "MLAU266459622"
        apply("stock", other, subresource_body("stock", "user_product_stock_MLAU266459622"), minutes=1)

        assert row_of(mlpub_pg, "stock", UP)["total_quantity"] == 2  # 2 + 0
        assert row_of(mlpub_pg, "stock", other)["total_quantity"] == 26  # 26 + 0

    def test_the_stock_split_is_stored_in_its_own_columns(self, mlpub_pg) -> None:
        """Real captured stock (selling_address 26, meli_facility 0): own and Full land in typed columns."""
        apply("stock", UP, subresource_body("stock", "user_product_stock_MLAU266459622"), minutes=1)

        row = row_of(mlpub_pg, "stock", UP)
        assert (row["own_quantity"], row["full_quantity"], row["total_quantity"]) == (26, 0, 26)

    def test_a_family_is_keyed_by_its_bigint_id_given_as_text_and_lists_its_user_products(self, mlpub_pg) -> None:
        body = family_body()
        apply("family", FAMILY, body, minutes=1)

        row = row_of(mlpub_pg, "family", FAMILY)
        assert row["family_id"] == 5385385211222674 and row["raw"] == body
        assert row["user_products_ids"] == ["MLAU245334053"]


class TestChange:
    def test_a_user_product_change_logs_one_row_for_the_user_product_with_no_item(self, mlpub_pg) -> None:
        """Real user product with its `name` changed."""
        old = up_body()
        new = copy.deepcopy(old)
        new["name"] = old["name"] + " (renombrado)"
        apply("user_product", UP, old, minutes=1)

        outcome = apply("user_product", UP, new, minutes=2)

        (entry,) = logs(mlpub_pg, "user_product")
        assert outcome.kind == "changed" and outcome.change_log_id == entry["id"]
        assert entry["entity_id"] == UP and entry["item_id"] is None and entry["kind"] == "change"
        assert entry["changed_paths"] == ["name"]
        assert "entries" not in entry["context"] and "official_store_id" not in entry["context"]
        assert row_of(mlpub_pg, "user_product", UP)["name"] == new["name"]

    def test_a_stock_change_names_the_location_that_moved(self, mlpub_pg) -> None:
        """Real stock with the selling_address quantity 2 -> 5."""
        old = stock_body()
        new = copy.deepcopy(old)
        next(loc for loc in new["locations"] if loc["type"] == "selling_address")["quantity"] = 5
        apply("stock", UP, old, minutes=1)

        apply("stock", UP, new, minutes=2)

        (entry,) = logs(mlpub_pg, "stock")
        assert entry["entity_id"] == UP and entry["item_id"] is None
        assert entry["changed_paths"] == ["locations[selling_address].quantity"]
        assert row_of(mlpub_pg, "stock", UP)["total_quantity"] == 5

    def test_a_full_stock_change_updates_the_split_columns_idempotently(self, mlpub_pg) -> None:
        """Real stock with the meli_facility quantity 0 -> 7: the columns follow; a replay changes nothing."""
        old = stock_body()
        new = copy.deepcopy(old)
        next(loc for loc in new["locations"] if loc["type"] == "meli_facility")["quantity"] = 7
        apply("stock", UP, old, minutes=1)

        apply("stock", UP, new, minutes=2)
        replay = apply("stock", UP, new, minutes=3)

        row = row_of(mlpub_pg, "stock", UP)
        assert (row["full_quantity"], row["own_quantity"], row["total_quantity"]) == (7, 2, 9)
        assert replay.kind == "unchanged" and len(logs(mlpub_pg, "stock")) == 1

    def test_a_stock_that_only_reorders_its_locations_is_unchanged(self, mlpub_pg) -> None:
        old = stock_body()
        reordered = copy.deepcopy(old)
        reordered["locations"].reverse()
        apply("stock", UP, old, minutes=1)

        outcome = apply("stock", UP, reordered, minutes=2)

        assert outcome.kind == "unchanged" and logs(mlpub_pg) == []

    def test_a_family_gaining_a_user_product_logs_it_by_the_family_id(self, mlpub_pg) -> None:
        """Real family with one user product id added."""
        old = family_body()
        new = copy.deepcopy(old)
        new["user_products_ids"].append("MLAU266459622")
        apply("family", FAMILY, old, minutes=1)

        apply("family", FAMILY, new, minutes=2)

        (entry,) = logs(mlpub_pg, "family")
        assert entry["entity_id"] == FAMILY and entry["item_id"] is None
        assert row_of(mlpub_pg, "family", FAMILY)["user_products_ids"] == ["MLAU245334053", "MLAU266459622"]

    def test_locations_sharing_a_type_fall_back_to_the_whole_array_in_the_change_log(self, mlpub_pg) -> None:
        """PINNING (the rule already holds, from the shared diff engine). Real stock with a second location
        of the same type added (no such payload was captured: `type` is unique in every capture). A keyed
        array whose key repeats cannot be followed element by element, so the change is reported at
        `locations`; the change is still logged and nothing breaks."""
        old = stock_body()
        new = copy.deepcopy(old)
        new["locations"].append({"type": "selling_address", "quantity": 9})
        apply("stock", UP, old, minutes=1)

        apply("stock", UP, new, minutes=2)

        (entry,) = logs(mlpub_pg, "stock")
        assert entry["changed_paths"] == ["locations"]
        assert row_of(mlpub_pg, "stock", UP)["total_quantity"] == 11

    @pytest.mark.parametrize("resource", ["user_product", "stock", "family"])
    def test_these_resources_raise_no_event_even_with_events_on(self, mlpub_pg, resource) -> None:
        """Stock zero-crossings are item events (`available_quantity`); these rows have no event rules."""
        set_setting("events.enabled", True, "test")
        key, old = {
            "user_product": (UP, up_body()),
            "stock": (UP, stock_body()),
            "family": (FAMILY, family_body()),
        }[resource]
        new = copy.deepcopy(old)
        new.update(
            {
                "user_product": {"name": "otro nombre"},
                "stock": {"stock_mode": "other"},
                "family": {"site_id": "MLB"},
            }[resource]
        )
        apply(resource, key, old, minutes=1)

        outcome = apply(resource, key, new, minutes=2)

        assert outcome.kind == "changed" and outcome.events == 0
        with mlpub_pg.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_item_events")).scalar() == 0


class TestNotFoundAndErrors:
    @pytest.mark.parametrize("resource, key", [("user_product", UP), ("stock", UP), ("family", FAMILY)])
    def test_a_404_marks_gone_once_keeps_the_raw_and_a_200_restores(self, mlpub_pg, resource, key) -> None:
        body = {"user_product": up_body, "stock": stock_body, "family": family_body}[resource]()
        apply(resource, key, body, minutes=1)

        first = apply(resource, key, NOT_FOUND_BODY, status=404, minutes=2)
        second = apply(resource, key, NOT_FOUND_BODY, status=404, minutes=3)
        restored = apply(resource, key, body, minutes=4)

        kinds = [entry["kind"] for entry in logs(mlpub_pg, resource)]
        assert (first.kind, second.kind, restored.kind) == ("gone", "unchanged", "restored")
        assert kinds == ["gone", "restored"]
        row = row_of(mlpub_pg, resource, key)
        assert row["raw"] == body and row["gone_at"] is None

    def test_a_first_404_is_never_existed_without_a_log(self, mlpub_pg) -> None:
        outcome = apply("stock", "MLAU1", NOT_FOUND_BODY, status=404, minutes=1)

        row = row_of(mlpub_pg, "stock", "MLAU1")
        assert outcome.kind == "never_existed" and row["never_existed"] is True and logs(mlpub_pg) == []

    def test_a_stock_403_is_recorded_with_status_and_body_and_keeps_the_state(self, mlpub_pg) -> None:
        """Synthetic transport fault: no 403 was captured; the body is a generic ML error."""
        body = stock_body()
        apply("stock", UP, body, minutes=1)
        error_body = {"message": "forbidden", "error": "forbidden", "status": 403, "cause": []}

        outcome = apply("stock", UP, error_body, status=403, minutes=2)

        row = row_of(mlpub_pg, "stock", UP)
        assert outcome.kind == "error_recorded"
        assert row["http_status"] == 403 and row["error_body"] == error_body and row["last_error"] == "HTTP 403"
        assert row["raw"] == body and row["total_quantity"] == 2 and row["gone_at"] is None
        assert logs(mlpub_pg) == []
