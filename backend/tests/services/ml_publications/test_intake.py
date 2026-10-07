"""Notification intake from the bridge `webhook_latest` (design D13).

Postgres only. Two schemas stand in for the two databases: `mlpub_pg` is the pricing core schema and
`bridge_pg` holds the real bridge DDL. Every row is a real captured `webhook_latest` row; a test that
puts it on a timeline changes only `received_at`/`resource` (docstring says so).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from app.core.config import settings
from app.services.ml_publications import intake, queue
from tests.services.ml_publications.conftest import load_fixture, put_webhook, webhook_row, WEBHOOK_SAMPLES

pytestmark = pytest.mark.postgres

SELLER = "413658225"  # user_id of every captured row
NOW = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
DEFAULT_TOPICS = {"items": {"kind": "item", "resources": ["bundle"]}}


def at(seconds: float) -> datetime:
    """A point on the test timeline, relative to NOW."""
    return NOW + timedelta(seconds=seconds)


def item_row(item_id: str, seconds: float, **overrides):
    """Real captured `items` row (real payload, resource and received_at changed)."""
    overrides.setdefault("resource", f"/items/{item_id}")
    return webhook_row("items", 0, received_at=str(at(seconds)), **overrides)


def run(bridge, *, topics=None, **kwargs) -> intake.IntakeResult:
    params = dict(seller_id=SELLER, batch=1000, overlap_seconds=120, overlap_batch=2000, now=NOW)
    params.update(kwargs)
    mappings = intake.topic_mappings(topics if topics is not None else DEFAULT_TOPICS)
    return intake.run_pass(mappings, bridge_engine=lambda: bridge, **params)


def set_cursor(engine, topic: str, seconds: float, resource: str = "") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_pub_intake_cursors (topic, cursor_received_at, cursor_resource) "
                "VALUES (:t, :a, :r) ON CONFLICT (topic) DO UPDATE SET cursor_received_at = :a, cursor_resource = :r"
            ),
            {"t": topic, "a": at(seconds), "r": resource},
        )


def cursor(engine, topic: str = "items"):
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT * FROM ml_pub_intake_cursors WHERE topic = :t"), {"t": topic}).mappings().first()
        )


def queued(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM ml_pub_refresh_queue ORDER BY entity_id")).mappings().all()
    return {r["entity_id"]: dict(r) for r in rows}


@pytest.fixture()
def env(mlpub_pg, bridge_pg, monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", SELLER)
    return mlpub_pg, bridge_pg


class TestResourcePatterns:
    """The captured resource strings of every mapped topic parse to the item id."""

    @pytest.mark.parametrize(
        "topic",
        ["items", "items_prices", "catalog_item_competition_status", "public_offers", "public_candidates"],
    )
    def test_every_captured_resource_of_a_mapped_topic_parses_to_its_item_id(self, topic) -> None:
        rows = [r for r in load_fixture(WEBHOOK_SAMPLES)["samples"] if r["topic"] == topic]
        assert rows
        for row in rows:
            item_id = intake.parse_resource(topic, row["resource"])
            assert item_id is not None and item_id.startswith("MLA") and item_id[3:].isdigit()
            assert item_id in row["resource"]

    @pytest.mark.parametrize(
        ("topic", "resource", "expected"),
        [
            ("items", "/items/MLA3510129282", "MLA3510129282"),
            ("items_prices", "/items/MLA2146684809/prices", "MLA2146684809"),
            ("catalog_item_competition_status", "/items/MLA1549873393/price_to_win", "MLA1549873393"),
            ("public_offers", "/seller-promotions/offers/OFFER-MLA2146684809-11568619217", "MLA2146684809"),
            (
                "public_candidates",
                "/seller-promotions/candidates/CANDIDATE-MLA1517412303-71656072178",
                "MLA1517412303",
            ),
        ],
    )
    def test_exact_captured_patterns(self, topic, resource, expected) -> None:
        assert intake.parse_resource(topic, resource) == expected

    @pytest.mark.parametrize(
        ("topic", "resource"),
        [
            ("items", "/items/MLA3510129282/prices"),  # another topic's shape
            ("items", "/items/not-an-id"),
            ("items", ""),
            ("items_prices", "/items/MLA1"),
            ("public_offers", "/seller-promotions/candidates/CANDIDATE-MLA1-2"),
        ],
    )
    def test_a_resource_off_the_pattern_does_not_parse(self, topic, resource) -> None:
        assert intake.parse_resource(topic, resource) is None


class TestTopicMap:
    def test_default_settings_map_only_the_items_topic(self) -> None:
        mappings = intake.topic_mappings(settings.ML_PUB_INTAKE_TOPICS)
        assert [m.topic for m in mappings] == ["items"]
        assert mappings[0].resources == ("bundle",)

    def test_topics_without_a_fixed_pattern_or_with_a_bad_entry_are_skipped(self) -> None:
        mappings = intake.topic_mappings(
            {
                "items_prices": {"kind": "item", "resources": ["prices", "sale_price"]},
                "stock-locations": {"kind": "user_product", "resources": ["stock"]},  # no sampled pattern yet
                "price_suggestion": {"kind": "item", "resources": ["bundle"]},  # never mapped
                "public_offers": {"kind": "item", "resources": ["nonsense"]},  # unknown resource name
                "items": "not-an-object",
            }
        )
        assert [(m.topic, m.resources) for m in mappings] == [("items_prices", ("prices", "sale_price"))]


class TestForwardPass:
    def test_a_thousand_collapsed_events_are_one_queue_entry(self, env) -> None:
        pricing, bridge = env
        for n in range(1000):  # the bridge upserts: one row per (topic, resource), latest wins
            put_webhook(bridge, item_row("MLA3510129282", -30 + n * 0.001))
        result = run(bridge)
        assert result.error is None
        entries = queued(pricing)
        assert list(entries) == ["MLA3510129282"]
        assert entries["MLA3510129282"]["lane"] == queue.LANE_NOTIFICATION
        assert entries["MLA3510129282"]["resources"] == ["bundle"]
        assert entries["MLA3510129282"]["source_received_at"] == at(-30 + 999 * 0.001)

    def test_first_run_starts_at_now_minus_overlap_and_stores_the_cursor(self, env) -> None:
        pricing, bridge = env
        put_webhook(bridge, item_row("MLA1000000001", -500))  # older than the window: backfill's job
        put_webhook(bridge, item_row("MLA1000000002", -60))
        run(bridge)
        assert list(queued(pricing)) == ["MLA1000000002"]
        assert cursor(pricing)["cursor_received_at"] == at(-60)

    def test_a_full_batch_always_advances_the_cursor_even_on_tied_timestamps(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        for suffix in ("1", "2", "3", "4", "5"):  # same received_at: the resource breaks the tie
            put_webhook(bridge, item_row(f"MLA200000000{suffix}", -50))
        result = run(bridge, batch=2)
        assert sorted(queued(pricing)) == [f"MLA200000000{n}" for n in range(1, 6)]
        assert result.stats.batches == 3  # 2 + 2 + 1, never the same rows twice
        assert cursor(pricing)["cursor_resource"] == "/items/MLA2000000005"
        assert cursor(pricing)["rows_read"] == 5

    def test_the_forward_read_is_strictly_after_the_cursor(self, env) -> None:
        pricing, bridge = env
        put_webhook(bridge, item_row("MLA3000000001", -50))
        set_cursor(pricing, "items", -50, "/items/MLA3000000001")  # the row sits exactly at the cursor
        result = run(bridge)
        assert result.stats.rows_read == 0 and result.stats.batches == 0
        assert cursor(pricing)["rows_read"] is None

    def test_the_cursor_only_moves_after_the_enqueue_commits(self, env, monkeypatch) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA4000000001", -50))

        def failing_enqueue(entries, session=None):
            session.execute(text("SELECT 1"))  # inside the same transaction as the cursor write
            raise RuntimeError("enqueue failed")

        real_enqueue = queue.enqueue
        monkeypatch.setattr(intake.queue, "enqueue", failing_enqueue)
        result = run(bridge)
        assert result.error and "enqueue failed" in result.error
        assert cursor(pricing)["cursor_received_at"] == at(-100)
        assert cursor(pricing)["rows_read"] is None
        monkeypatch.setattr(intake.queue, "enqueue", real_enqueue)
        run(bridge)  # the retry reads the same row again: nothing was skipped
        assert list(queued(pricing)) == ["MLA4000000001"]

    def test_foreign_seller_is_skipped_and_counted(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        foreign = item_row("MLA5000000001", -50)
        foreign["payload"]["user_id"] = 999  # real payload, one field changed
        put_webhook(bridge, foreign)
        put_webhook(bridge, item_row("MLA5000000002", -40))
        result = run(bridge)
        assert list(queued(pricing)) == ["MLA5000000002"]
        assert result.stats.skipped_foreign_seller == 1
        assert cursor(pricing)["skipped_foreign_seller"] == 1

    def test_an_unparsable_resource_of_a_mapped_topic_is_counted_and_not_fatal(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA6000000001", -50, resource="/items/MLA6000000001/unexpected"))
        put_webhook(bridge, item_row("MLA6000000002", -40))
        result = run(bridge)
        assert list(queued(pricing)) == ["MLA6000000002"]
        assert result.error is None
        assert result.stats.unparsed == 1
        assert cursor(pricing)["unparsed"] == 1
        assert cursor(pricing)["cursor_resource"] == "/items/MLA6000000002"

    def test_unmapped_topics_are_never_read(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, webhook_row("price_suggestion", 0, received_at=str(at(-50))))
        put_webhook(bridge, item_row("MLA7000000001", -40))
        seen: list[str] = []

        @event.listens_for(bridge, "before_cursor_execute")
        def capture(conn, cursor_, statement, parameters, context, executemany):  # noqa: ANN001
            seen.append(f"{statement} {parameters}")

        run(bridge)
        selects = [s for s in seen if "FROM webhook_latest" in s]
        assert selects and not [s for s in selects if "price_suggestion" in s]
        assert all("'items'" in s for s in selects)
        assert list(queued(pricing)) == ["MLA7000000001"]

    def test_a_non_default_topic_enqueues_its_own_resources(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-50))))
        topics = {"items_prices": {"kind": "item", "resources": ["prices", "sale_price"]}}
        run(bridge, topics=topics)
        (entry,) = queued(pricing).values()
        assert entry["resources"] == ["prices", "sale_price"]


class TestSatisfiedFilter:
    def put_item(self, engine, item_id: str, fetched_started: datetime | None) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_items (item_id, fetched_request_started_at) VALUES (:i, :f)"),
                {"i": item_id, "f": fetched_started},
            )

    def test_a_row_the_state_already_covers_is_skipped_and_counted(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA8000000001", -50))  # fetched after the notification
        put_webhook(bridge, item_row("MLA8000000002", -40))  # fetched before it
        put_webhook(bridge, item_row("MLA8000000003", -30))  # never fetched
        self.put_item(pricing, "MLA8000000001", at(-49))
        self.put_item(pricing, "MLA8000000002", at(-41))
        result = run(bridge)
        assert sorted(queued(pricing)) == ["MLA8000000002", "MLA8000000003"]
        assert result.stats.skipped_satisfied == 1
        assert cursor(pricing)["skipped_satisfied"] == 1

    def test_a_fetch_that_started_exactly_at_the_notification_counts_as_satisfied(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA8100000001", -50))
        self.put_item(pricing, "MLA8100000001", at(-50))
        run(bridge)
        assert queued(pricing) == {}

    def test_sub_resource_topics_are_not_filtered_by_the_item_core_state(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        row = webhook_row("items_prices", 0, received_at=str(at(-50)))
        put_webhook(bridge, row)
        item_id = intake.parse_resource("items_prices", row["resource"])
        self.put_item(pricing, item_id, at(-10))  # the core was fetched, the prices were not
        run(bridge, topics={"items_prices": {"kind": "item", "resources": ["prices"]}})
        assert list(queued(pricing)) == [item_id]


class TestOverlapPass:
    def test_a_late_committing_row_behind_the_cursor_is_enqueued(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")  # cursor at T
        put_webhook(bridge, item_row("MLA9000000001", -2))  # committed late with received_at T-2s
        result = run(bridge)
        assert list(queued(pricing)) == ["MLA9000000001"]
        assert result.stats.overlap_enqueued == 1
        assert cursor(pricing)["cursor_received_at"] == at(0)  # the overlap never moves the cursor
        assert cursor(pricing)["cursor_resource"] == "/items/MLA9000000009"

    def test_rows_older_than_the_overlap_window_are_left_alone(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")
        put_webhook(bridge, item_row("MLA9100000001", -300))
        run(bridge)
        assert queued(pricing) == {}

    def test_an_overlap_over_its_limit_is_counted_and_never_looped_on(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")
        for n in range(1, 6):
            put_webhook(bridge, item_row(f"MLA920000000{n}", -10 + n))
        result = run(bridge, overlap_batch=2)
        assert result.stats.overlap_truncated == 1
        assert result.stats.overlap_rows == 2
        assert len(queued(pricing)) == 2
        assert cursor(pricing)["cursor_received_at"] == at(0)

    def test_a_truncated_overlap_keeps_the_rows_nearest_the_cursor(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")
        for n in range(1, 6):  # received_at -9, -8, ... -5: the newest ones are the likeliest late arrivals
            put_webhook(bridge, item_row(f"MLA950000000{n}", -10 + n))
        run(bridge, overlap_batch=2)
        assert sorted(queued(pricing)) == ["MLA9500000004", "MLA9500000005"]

    def test_the_overlap_skips_what_the_store_already_fetched(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")
        put_webhook(bridge, item_row("MLA9300000001", -2))
        with pricing.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_items (item_id, fetched_request_started_at) VALUES ('MLA9300000001', :f)"),
                {"f": at(-1)},
            )
        result = run(bridge)
        assert queued(pricing) == {}
        assert result.stats.overlap_rows == 1 and result.stats.overlap_enqueued == 0

    def test_the_overlap_does_not_inflate_the_stored_counters(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", 0, "/items/MLA9000000009")
        put_webhook(bridge, item_row("MLA9400000001", -2))
        for _ in range(3):
            run(bridge)
        assert cursor(pricing)["rows_read"] is None


class TestOverlapMemory:
    """The overlap re-reads the same rows every pass; rows already handled must not be enqueued again
    (each re-enqueue bumps the entry version and can requeue an in-flight claim)."""

    PRICES = {"items_prices": {"kind": "item", "resources": ["prices"]}}  # no item-core satisfied filter

    def versions(self, engine) -> dict[str, int]:
        return {k: v["version"] for k, v in queued(engine).items()}

    def test_a_row_already_enqueued_by_the_forward_pass_is_not_enqueued_again_by_the_next_overlap(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-50))))
        memory = intake.OverlapMemory()
        run(bridge, topics=self.PRICES, memory=memory)
        before = self.versions(pricing)
        run(bridge, topics=self.PRICES, memory=memory)  # the row is now behind the cursor, inside the window
        run(bridge, topics=self.PRICES, memory=memory)
        assert self.versions(pricing) == before

    def test_a_late_row_is_enqueued_once_across_repeated_overlap_passes(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", 0, "/items/MLA9999999999/prices")
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-2))))
        memory = intake.OverlapMemory()
        run(bridge, topics=self.PRICES, memory=memory)
        after_first = self.versions(pricing)
        assert len(after_first) == 1
        for _ in range(3):
            run(bridge, topics=self.PRICES, memory=memory)
        assert self.versions(pricing) == after_first

    def test_a_new_delivery_of_the_same_resource_is_enqueued_again(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-50))))
        memory = intake.OverlapMemory()
        run(bridge, topics=self.PRICES, memory=memory)
        before = self.versions(pricing)
        # real row, received_at changed: ML sent the notification again, the bridge kept the latest
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-1))))
        run(bridge, topics=self.PRICES, memory=memory)
        (item,) = before
        assert self.versions(pricing)[item] == before[item] + 1

    def test_the_memory_forgets_rows_that_left_the_window(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-50))))
        memory = intake.OverlapMemory()
        run(bridge, topics=self.PRICES, memory=memory)
        assert memory.size() == 1
        later = webhook_row("items_prices", 1, received_at=str(at(1000)))
        put_webhook(bridge, later)  # the cursor moves 1000 s on: the first row is far behind the window
        run(bridge, topics=self.PRICES, memory=memory, now=at(1000))
        assert memory.size() == 1


class TestConcurrentIntake:
    def test_a_cursor_that_another_pass_already_moved_further_is_not_pulled_back(self, env, monkeypatch) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA1500000001", -50))
        real_read = intake._read
        calls = {"n": 0}

        def read_then_lose_the_race(*args, **kwargs):
            rows = real_read(*args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 1:  # only the forward read: a second process gets further before our write
                set_cursor(pricing, "items", 10, "/items/MLA1500000009")
            return rows

        monkeypatch.setattr(intake, "_read", read_then_lose_the_race)
        result = run(bridge, overlap_seconds=0)
        row = cursor(pricing)
        assert row["cursor_received_at"] == at(10) and row["cursor_resource"] == "/items/MLA1500000009"
        assert row["rows_read"] is None  # the losing pass does not add to the counters
        # The other process already covered everything up to its cursor: the loser neither re-enqueues
        # (each repeat bumps the entry version) nor keeps looping from its stale position.
        assert queued(pricing) == {}
        assert result.stats.cursor_conflicts == 1 and result.stats.batches == 0


class TestFailureAndSafety:
    def test_an_unreachable_bridge_is_logged_leaves_the_cursor_and_does_not_raise(self, env) -> None:
        pricing, _bridge = env
        set_cursor(pricing, "items", -100)

        def unreachable():
            raise RuntimeError("ML_WEBHOOK_DB_URL is not configured")

        result = intake.run_pass(
            intake.topic_mappings(DEFAULT_TOPICS),
            bridge_engine=unreachable,
            seller_id=SELLER,
            now=NOW,
        )
        assert result.error == "bridge_unavailable"
        assert cursor(pricing)["cursor_received_at"] == at(-100)
        assert queued(pricing) == {}

    def test_a_bridge_query_failure_leaves_the_cursor(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        with bridge.begin() as conn:
            conn.execute(text("ALTER TABLE webhook_latest RENAME TO webhook_latest_gone"))
        result = run(bridge)
        assert result.error == "bridge_unavailable"
        assert cursor(pricing)["cursor_received_at"] == at(-100)

    def test_without_a_configured_seller_nothing_is_read(self, env) -> None:
        pricing, bridge = env
        put_webhook(bridge, item_row("MLA1100000001", -50))
        result = run(bridge, seller_id=None)
        assert result.error == "seller_not_configured"
        assert cursor(pricing) is None and queued(pricing) == {}

    def test_the_bridge_is_only_ever_read(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA1200000001", -50))
        seen: list[str] = []

        @event.listens_for(bridge, "before_cursor_execute")
        def capture(conn, cursor_, statement, parameters, context, executemany):  # noqa: ANN001
            seen.append(statement.strip().split()[0].upper())

        run(bridge)
        assert seen[0] == "SET"  # SET TRANSACTION READ ONLY comes first on every bridge connection
        assert set(seen) <= {"SET", "SELECT"}
        with bridge.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM webhook_latest")).scalar() == 1

    def test_the_bridge_connection_is_a_read_only_transaction(self, env) -> None:
        _pricing, bridge = env
        with intake.open_read_only(bridge) as conn:
            with pytest.raises(Exception, match="read-only"):
                conn.execute(text("DELETE FROM webhook_latest"))

    def test_keep_going_false_stops_before_any_read(self, env) -> None:
        pricing, bridge = env
        put_webhook(bridge, item_row("MLA1300000001", -50))
        result = run(bridge, keep_going=lambda: False)
        assert result.error is None and result.stats.rows_read == 0
        assert queued(pricing) == {}

    def test_duplicate_and_out_of_order_events_converge_on_one_entry(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items", -100)
        put_webhook(bridge, item_row("MLA1400000001", -20))
        put_webhook(bridge, item_row("MLA1400000002", -50))  # arrives out of order, older
        run(bridge)
        set_cursor(pricing, "items", -100)  # replay: the same rows are read again
        run(bridge)
        entries = queued(pricing)
        assert sorted(entries) == ["MLA1400000001", "MLA1400000002"]
        assert entries["MLA1400000001"]["source_received_at"] == at(-20)


PROMOTION_TOPICS = {
    "public_offers": {"kind": "item", "resources": ["promotions"]},
    "public_candidates": {"kind": "item", "resources": ["promotions"]},
}
OFFER_ITEM, CANDIDATE_ITEM = "MLA2146684809", "MLA1517412303"  # the first captured row of each topic


class TestPromotionTopics:
    """`public_offers` / `public_candidates` mapped to a promotions-only refresh, debounced 60 s (design D14)."""

    def put_both(self, bridge, pricing, *, offer_at: float = -50, candidate_at: float = -40) -> None:
        for topic in PROMOTION_TOPICS:
            set_cursor(pricing, topic, -100)
        put_webhook(bridge, webhook_row("public_offers", 0, received_at=str(at(offer_at))))
        put_webhook(bridge, webhook_row("public_candidates", 0, received_at=str(at(candidate_at))))

    def test_a_captured_row_of_each_topic_enqueues_its_item_with_promotions_only_and_a_60_second_debounce(
        self, env
    ) -> None:
        pricing, bridge = env
        self.put_both(bridge, pricing)

        result = run(bridge, topics=PROMOTION_TOPICS)

        entries = queued(pricing)
        assert sorted(entries) == [CANDIDATE_ITEM, OFFER_ITEM]
        assert result.stats.enqueued == 2
        offer, candidate = entries[OFFER_ITEM], entries[CANDIDATE_ITEM]
        assert (offer["resources"], offer["lane"]) == (["promotions"], queue.LANE_NOTIFICATION)
        assert (candidate["resources"], candidate["lane"]) == (["promotions"], queue.LANE_NOTIFICATION)
        assert offer["not_before"] == at(-50) + timedelta(seconds=60)
        assert candidate["not_before"] == at(-40) + timedelta(seconds=60)
        assert (offer["source_received_at"], candidate["source_received_at"]) == (at(-50), at(-40))

    def test_the_debounce_keeps_the_entry_unclaimable_until_it_elapses(self, env) -> None:
        pricing, bridge = env
        self.put_both(bridge, pricing, offer_at=-10, candidate_at=-10)  # NOW - 10 s: not due until NOW + 50 s
        run(bridge, topics=PROMOTION_TOPICS)

        with pricing.connect() as conn:
            due = conn.execute(text("SELECT count(*) FROM ml_pub_refresh_queue WHERE not_before <= :t"), {"t": NOW})
            assert due.scalar() == 0
            due = conn.execute(
                text("SELECT count(*) FROM ml_pub_refresh_queue WHERE not_before <= :t"),
                {"t": NOW + timedelta(seconds=51)},
            )
            assert due.scalar() == 2

    def test_a_flood_of_offers_and_candidates_of_one_item_collapses_into_one_entry(self, env) -> None:
        """Real captured rows; the flood changes only the `resource` offer/candidate ids (payload mirrored)."""
        pricing, bridge = env
        for topic in PROMOTION_TOPICS:
            set_cursor(pricing, topic, -100)
        for index, offer_id in enumerate(("11568619217", "11568619218", "11568619219")):
            resource = f"/seller-promotions/offers/OFFER-{OFFER_ITEM}-{offer_id}"
            put_webhook(bridge, webhook_row("public_offers", 0, resource=resource, received_at=str(at(-50 + index))))
        resource = f"/seller-promotions/candidates/CANDIDATE-{OFFER_ITEM}-71656072178"
        put_webhook(bridge, webhook_row("public_candidates", 0, resource=resource, received_at=str(at(-40))))

        result = run(bridge, topics=PROMOTION_TOPICS)

        (entry,) = queued(pricing).values()
        assert entry["entity_id"] == OFFER_ITEM and entry["resources"] == ["promotions"]
        assert entry["version"] == 4  # four notifications merged by the queue key
        assert entry["not_before"] == at(-50) + timedelta(seconds=60)  # the first one sets the debounce
        assert result.stats.enqueued == 4

    def test_the_debounce_is_an_env_setting_with_a_60_second_default(self, env, monkeypatch) -> None:
        pricing, bridge = env
        assert settings.ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS == 60
        monkeypatch.setattr(settings, "ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS", 120)
        self.put_both(bridge, pricing)

        run(bridge, topics=PROMOTION_TOPICS)

        assert queued(pricing)[OFFER_ITEM]["not_before"] == at(-50) + timedelta(seconds=120)

    def test_a_zero_debounce_makes_the_entry_claimable_at_once(self, env, monkeypatch) -> None:
        pricing, bridge = env
        monkeypatch.setattr(settings, "ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS", 0)
        self.put_both(bridge, pricing)

        run(bridge, topics=PROMOTION_TOPICS)

        assert queued(pricing)[OFFER_ITEM]["not_before"] <= datetime.now(timezone.utc)

    def test_a_promotions_row_is_not_judged_by_the_item_core_fetch(self, env) -> None:
        pricing, bridge = env
        self.put_both(bridge, pricing)
        with pricing.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_items (item_id, fetched_request_started_at) VALUES (:i, :f)"),
                {"i": OFFER_ITEM, "f": at(-10)},
            )

        result = run(bridge, topics=PROMOTION_TOPICS)

        assert OFFER_ITEM in queued(pricing)  # the core was fetched after it, the promotions were not
        assert result.stats.skipped_satisfied == 0

    def test_a_mapping_that_asks_for_more_than_promotions_is_not_debounced(self, env) -> None:
        pricing, bridge = env
        self.put_both(bridge, pricing)
        topics = {"public_offers": {"kind": "item", "resources": ["bundle", "promotions"]}}

        run(bridge, topics=topics)

        entry = queued(pricing)[OFFER_ITEM]
        assert entry["resources"] == ["bundle", "promotions"]
        assert entry["not_before"] <= datetime.now(timezone.utc)  # `now()` at enqueue time: claimable at once

    def test_a_price_topic_is_not_debounced(self, env) -> None:
        pricing, bridge = env
        set_cursor(pricing, "items_prices", -100)
        put_webhook(bridge, webhook_row("items_prices", 0, received_at=str(at(-50))))

        run(bridge, topics={"items_prices": {"kind": "item", "resources": ["prices"]}})

        (entry,) = queued(pricing).values()
        assert entry["not_before"] <= datetime.now(timezone.utc)

    def test_the_default_map_reads_neither_promotion_topic(self, env) -> None:
        pricing, bridge = env
        self.put_both(bridge, pricing)
        set_cursor(pricing, "items", -100)

        result = run(bridge)  # default topics: items only

        assert queued(pricing) == {}
        assert result.stats.rows_read == 0
        assert [m.topic for m in intake.topic_mappings(settings.ML_PUB_INTAKE_TOPICS)] == ["items"]
