"""Replenishment wired into the generic store (P4b): registry, fetcher, plan, 206 handling, failures.

Everything runs on the real captures of 2026-10-08 (`replenishment_20261008.json`). The 206 and the 403 are
synthetic transitions of a real body (no 206 or 403 showed up in the capture): the partial answer carries the
`x-content-missing` header the reference app documents, the 403 is a transport fault.

The capture proved ML answers 200 WITHOUT `x-caller-id` / `x-caller-siteId`, so the fetcher sends no extra
request headers: `SubFetcher` and `MlHttpClient` are unchanged.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import bundle, diff
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import (
    REFRESH_RESOURCES,
    RESOURCES,
    USER_PRODUCT_KIND,
)
from app.services.ml_publications.subresource_store import MODELS, apply_subresource
from tests.services.ml_publications.conftest import FIXTURES_DIR, load_fixture

FIXTURE = "replenishment_20261008.json"
T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
UP = "MLAU228712304"


def body_of(name: str = "full_1") -> dict:
    for call in load_fixture(FIXTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call["body"])
    raise KeyError(name)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def response(body, minutes: float = 0, status: int = 200, headers: dict | None = None) -> MlResponse:
    received = at(minutes)
    return MlResponse(
        endpoint="replenishment",
        status=status,
        body=body,
        headers=headers or {},
        request_started_at=received - timedelta(seconds=1),
        received_at=received,
    )


def apply(body, minutes: float = 0, status: int = 200, headers: dict | None = None, key: str = UP):
    return apply_subresource(RESOURCES["replenishment"], (key,), response(body, minutes, status, headers))


def row_of(engine, key: str = UP):
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT * FROM ml_user_product_replenishment WHERE user_product_id = :k"), {"k": key})
            .mappings()
            .first()
        )


class TestRegistry:
    def test_it_is_registered_with_the_captured_fixture_and_the_user_product_key(self) -> None:
        spec = RESOURCES["replenishment"]
        assert spec.key_columns == ("user_product_id",)
        assert spec.fixture == FIXTURE and (FIXTURES_DIR / spec.fixture).exists()
        assert MODELS["replenishment"].__tablename__ == "ml_user_product_replenishment"

    def test_only_the_content_missing_response_header_is_captured(self) -> None:
        assert RESOURCES["replenishment"].response_headers == ("x-content-missing",)
        assert all(spec.response_headers == () for name, spec in RESOURCES.items() if name != "replenishment")

    def test_the_weekly_history_is_keyed_by_its_start_date_through_a_nested_path(self) -> None:
        keys = RESOURCES["replenishment"].array_keys
        assert keys == diff.array_keys_for("replenishment") == {"sales.sales_history": ("start_date",)}

    def test_a_change_in_one_week_is_reported_at_that_week_not_as_the_whole_array(self) -> None:
        old, new = body_of(), body_of()
        week = new["sales"]["sales_history"][0]
        week["units_sold"] += 5
        changes = diff.diff(old, new, RESOURCES["replenishment"])
        assert [c.path for c in changes] == [f"sales.sales_history[{week['start_date']}].units_sold"]

    def test_it_is_a_canonical_refresh_name(self) -> None:
        assert "replenishment" in REFRESH_RESOURCES


class TestFetcher:
    def test_it_asks_the_documented_endpoint_for_a_user_product_with_no_extra_headers(self) -> None:
        fetcher = bundle.FETCHERS["replenishment"]
        assert fetcher.entity == USER_PRODUCT_KIND
        assert fetcher.request(UP) == (f"/marketplace/fbm/user-products/{UP}/replenishment", {"country": "AR"})
        assert {f.name for f in dataclasses.fields(fetcher)} == {"resource", "path", "params", "entity"}

    def test_it_is_sweep_only_so_the_bundle_never_includes_it(self) -> None:
        assert "replenishment" in bundle.SWEEP_ONLY
        plan = bundle.plan(("bundle",), ["core", "replenishment"], kind=USER_PRODUCT_KIND)
        assert dict(plan.wanted) == {} and plan.dropped == {"replenishment"}

    def test_a_named_user_product_entry_fetches_it_and_bypasses_the_minimum_age(self) -> None:
        plan = bundle.plan(("replenishment",), ["core", "replenishment"], kind=USER_PRODUCT_KIND)
        assert dict(plan.wanted) == {"replenishment": True}

    def test_a_named_item_entry_reaches_it_through_the_user_product_of_the_item(self) -> None:
        plan = bundle.plan(("replenishment",), ["core", "replenishment"])
        assert dict(plan.wanted) == {"replenishment": True} and plan.needs_core is False

    def test_it_is_inert_until_listed_in_bundle_resources(self) -> None:
        assert "replenishment" not in settings.ML_PUB_BUNDLE_RESOURCES
        for kind in ("item", USER_PRODUCT_KIND):
            plan = bundle.plan(("replenishment",), list(settings.ML_PUB_BUNDLE_RESOURCES), kind=kind)
            assert dict(plan.wanted) == {} and plan.dropped == {"replenishment"}

    def test_its_minimum_age_defaults_to_a_day(self) -> None:
        assert bundle.min_age_seconds("replenishment", settings.ML_PUB_MIN_AGE_SECONDS) == 86400


@pytest.mark.postgres
class TestStoredAnswers:
    def test_a_200_stores_the_typed_columns_as_not_partial(self, mlpub_pg) -> None:
        outcome = apply(body_of(), minutes=1, headers={})
        row = row_of(mlpub_pg)
        assert outcome.kind == "first_seen"
        assert (row["partial"], row["content_missing"], row["units_30d"], row["units_7d"]) == (False, None, 311, 38)
        assert row["raw"] == body_of() and row["http_status"] == 200

    def test_a_206_is_ok_and_partial_with_what_ml_said_is_missing(self, mlpub_pg) -> None:
        outcome = apply(body_of(), minutes=1, status=206, headers={"x-content-missing": "sales_history"})
        row = row_of(mlpub_pg)
        assert outcome.kind == "first_seen" and row["http_status"] == 206 and row["last_error"] is None
        assert (row["partial"], row["content_missing"]) == (True, "sales_history")
        assert row["units_30d"] == 311

    def test_a_later_200_with_the_same_body_clears_the_partial_flag(self, mlpub_pg) -> None:
        apply(body_of(), minutes=1, status=206, headers={"x-content-missing": "sales_history"})
        outcome = apply(body_of(), minutes=2, headers={})
        row = row_of(mlpub_pg)
        assert outcome.kind == "unchanged"
        assert (row["partial"], row["content_missing"]) == (False, None)

    def test_a_user_product_outside_full_stores_null_sales_without_an_error(self, mlpub_pg) -> None:
        outcome = apply(body_of("non_full_1"), minutes=1, key="MLAU1")
        row = row_of(mlpub_pg, "MLAU1")
        assert outcome.kind == "first_seen" and row["last_error"] is None
        assert (row["units_30d"], row["units_7d"], row["partial"]) == (None, None, False)

    def test_a_weekly_change_is_logged_at_the_week(self, mlpub_pg) -> None:
        apply(body_of(), minutes=1)
        newer = body_of()
        week = newer["sales"]["sales_history"][0]
        week["units_sold"] += 5
        outcome = apply(newer, minutes=2)
        with mlpub_pg.connect() as conn:
            paths = conn.execute(text("SELECT changes FROM ml_change_log WHERE resource_type = 'replenishment'"))
            logged = str(paths.scalar())
        assert outcome.kind == "changed" and f"sales.sales_history[{week['start_date']}].units_sold" in logged


@pytest.mark.postgres
class TestFailureKeepsPreviousData:
    @pytest.mark.parametrize("status", [403, 429, 500])
    def test_an_error_answer_records_the_error_and_keeps_the_stored_data(self, mlpub_pg, status) -> None:
        apply(body_of(), minutes=1)
        before = row_of(mlpub_pg)
        outcome = apply({"message": "boom", "status": status}, minutes=2, status=status)
        row = row_of(mlpub_pg)
        assert outcome.kind == "error_recorded"
        assert row["http_status"] == status and row["last_error"]
        for column in ("raw", "raw_hash", "units_30d", "units_7d", "gmv_30d", "total_stock", "partial"):
            assert row[column] == before[column], column

    def test_a_malformed_answer_keeps_the_stored_data_and_records_why(self, mlpub_pg) -> None:
        apply(body_of(), minutes=1)
        outcome = apply({"identifiers": {}}, minutes=2)  # a 200 with no `sales` key at all
        row = row_of(mlpub_pg)
        assert outcome.kind == "error_recorded" and row["last_error"].startswith("malformed")
        assert row["units_30d"] == 311

    def test_a_404_marks_it_gone_and_keeps_the_last_raw(self, mlpub_pg) -> None:
        apply(body_of(), minutes=1)
        outcome = apply({"status": 404, "error": "not_found"}, minutes=2, status=404)
        row = row_of(mlpub_pg)
        assert outcome.kind == "gone" and row["gone_at"] is not None and row["raw"] == body_of()
