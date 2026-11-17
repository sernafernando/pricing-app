"""Verifier probes for #2305: change-driven catalog-competition enqueue, pinned as regression tests.

Postgres only. Bodies are the store's captured ones re-keyed to synthetic MLA ids (a deep copy with `id` changed);
snapshot rows are synthetic.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.services import catalog_competition_refresh_queue as queue
from app.services.ml_publications import store as store_module
from tests.services.ml_publications.conftest import sample_item, subresource_body
from tests.services.ml_publications.test_store_catalog_competition_enqueue import (
    apply_item,
    env,  # noqa: F401 — the fixture
    pending,
)
from tests.services.ml_publications.test_subresource_store import apply as apply_sub
from tests.services.ml_publications.test_subresource_store import logs

pytestmark = pytest.mark.postgres

CAPTURED_CATALOG = "MLA882393030"  # captured active catalog listing
LISTING = "MLA1000000001"


def catalog_item(item_id: str = LISTING, price_delta: float = 0.0) -> dict:
    body = sample_item(CAPTURED_CATALOG)
    body["id"] = item_id
    body["price"] = float(body["price"]) + price_delta
    return body


def prices(item_id: str, amount_delta: float = 0.0) -> dict:
    body = copy.deepcopy(subresource_body("prices", "prices_MLA874027718"))
    if "id" in body:
        body["id"] = item_id
    if amount_delta:
        body["prices"][0]["amount"] = float(body["prices"][0]["amount"]) + amount_delta
    return body


class TestProbes:
    def test_a_prices_change_on_an_active_catalog_listing_enqueues_it(self, env) -> None:  # noqa: F811
        apply_item(catalog_item(), LISTING, minutes=0)
        apply_sub("prices", LISTING, prices(LISTING), minutes=1)

        apply_sub("prices", LISTING, prices(LISTING, amount_delta=500.0), minutes=2)

        assert [r["kind"] for r in logs(env, "prices")] == ["change"]
        assert [r["mla"] for r in pending(env)] == [LISTING]

    def test_ten_changes_within_a_minute_leave_ten_log_rows_one_queue_row_and_the_first_due_time(
        self,
        env,  # noqa: F811
    ) -> None:
        apply_item(catalog_item(), LISTING, minutes=0)
        apply_item(catalog_item(price_delta=1.0), LISTING, minutes=0.1)
        (first,) = pending(env)

        for n in range(2, 11):
            apply_item(catalog_item(price_delta=float(n)), LISTING, minutes=0.1 * n)

        assert [r["kind"] for r in logs(env, "item")] == ["change"] * 10
        (row,) = pending(env)
        assert row["due_at"] == first["due_at"]

    def test_an_error_snapshot_inside_the_gap_blocks_a_new_enqueue(self, env) -> None:  # noqa: F811
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_catalog_competition (mla, fecha_consulta, fetch_status, competitors, "
                    "competitor_count, error_detail) VALUES (:m, now() - interval '10 minutes', 'error', '[]', 0, "
                    "'synthetic failure')"
                ),
                {"m": LISTING},
            )
        apply_item(catalog_item(), LISTING, minutes=0)

        apply_item(catalog_item(price_delta=100.0), LISTING, minutes=5)

        assert pending(env) == []

    def test_a_change_while_the_worker_holds_the_row_survives_its_settle(self, env) -> None:  # noqa: F811
        apply_item(catalog_item(), LISTING, minutes=0)
        apply_item(catalog_item(price_delta=1.0), LISTING, minutes=1)
        (queued,) = pending(env)
        with store_module.database.get_background_db() as db:
            claim = queue.claim_one(db, queued["due_at"] + timedelta(seconds=1))
        assert claim is not None and claim.mla == LISTING

        apply_item(catalog_item(price_delta=2.0), LISTING, minutes=2)  # the fetch is in flight
        with store_module.database.get_background_db() as db:
            queue.drop(db, claim)  # the worker settles its successful refresh

        (row,) = pending(env)
        assert row["mla"] == LISTING and row["due_at"] < claim.leased_until
