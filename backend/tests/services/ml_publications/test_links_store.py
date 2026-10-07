"""Product links against a real Postgres: evaluation, manual-wins, history, events, hook, coverage.

Items are real captures (a transition is one real payload with the named field changed).
`productos_erp` rows are plain test data: our own table, not an ML payload.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from app.core import database
from app.models.ml_publications import MlItemProductLink
from app.models.producto import ProductoERP
from app.services.ml_publications import events_store, links
from app.services.ml_publications import store as store_module
from app.services.ml_publications.mappers import map_item, map_variations
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import bulk_item, item_with_variations, sample_item
from tests.services.ml_publications.test_store_apply_fetch import apply, item_row, only_not_found

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
SKU_A = "6932391923412"  # real SELLER_SKU of MLA882393030 and MLA874027718
SKU_B = "6932391923481"  # real SELLER_SKU of MLA935110613
ITEM = "MLA882393030"


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture()
def env(mlpub_pg):
    """The real link table plus a `productos_erp` table built from the real model."""
    ProductoERP.__table__.create(bind=mlpub_pg)
    return mlpub_pg


@pytest.fixture()
def events_on(env):
    set_setting("events.enabled", True, "test")
    return env


def add_product(engine, item_id: int, codigo: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO productos_erp (item_id, codigo) VALUES (:i, :c)"), {"i": item_id, "c": codigo})


def remove_product(engine, item_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM productos_erp WHERE item_id = :i"), {"i": item_id})


def put_link(engine, item_id: str, variation_id: int, source: str, status: str, product: int | None, **extra) -> None:
    columns = {
        "item_id": item_id,
        "variation_id": variation_id,
        "source": source,
        "match_status": status,
        "producto_item_id": product,
        "linked_at": at(-60),
        **extra,
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO ml_item_product_links ({', '.join(columns)}) "
                f"VALUES ({', '.join(':' + c for c in columns)})"
            ),
            columns,
        )


def link(engine, item_id: str = ITEM, variation_id: int = 0):
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM ml_item_product_links WHERE item_id = :i AND variation_id = :v"),
                {"i": item_id, "v": variation_id},
            )
            .mappings()
            .first()
        )


def link_rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM ml_item_product_links ORDER BY item_id, variation_id")).mappings().all()


def log_rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM ml_change_log WHERE resource_type = 'product_link'")).mappings().all()


def event_rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM ml_item_events ORDER BY id")).mappings().all()


def evaluate(body: dict, *, minutes: float = 0, events: bool = False, force: bool = False) -> links.EvaluationResult:
    typed = map_item(body)
    with database.get_background_db() as db:
        return links.evaluate_item(
            db, typed["item_id"], typed, map_variations(body), now=at(minutes), events_enabled=events, force=force
        )


class TestFirstEvaluation:
    def test_writes_a_sku_auto_row_with_the_suggestion_and_no_history(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)

        result = evaluate(sample_item(ITEM), minutes=1, events=True)

        row = link(events_on)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "linked", 41)
        assert (row["matched_sku"], row["sku_field"]) == (SKU_A, "seller_sku_attr")
        assert (row["suggestion_status"], row["suggested_producto_item_id"], row["suggestion_candidates"]) == (
            "linked",
            41,
            1,
        )
        assert (row["evaluated_sku_key"], row["evaluated_at"], row["linked_at"], row["linked_by"]) == (
            SKU_A,
            at(1),
            at(1),
            None,
        )
        assert log_rows(events_on) == [] and event_rows(events_on) == []
        assert result.created == 1 and result.changed == 0

    def test_an_unmatched_item_is_stored_as_unmatched_with_the_key_that_was_not_found(self, env) -> None:
        evaluate(sample_item(ITEM))
        row = link(env)
        assert (row["match_status"], row["producto_item_id"], row["matched_sku"]) == ("unmatched", None, SKU_A)

    def test_a_conflict_records_every_candidate_and_picks_none(self, env) -> None:
        add_product(env, 9, SKU_A)
        add_product(env, 5, SKU_A)
        evaluate(sample_item(ITEM))
        row = link(env)
        assert (row["match_status"], row["producto_item_id"], row["candidate_ids"]) == ("conflict", None, [5, 9])
        assert (row["suggestion_status"], row["suggestion_candidates"]) == ("conflict", 2)

    def test_an_item_with_variations_gets_one_row_per_variation_and_none_at_item_level(self, env) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"  # real payload, one field changed
        add_product(env, 7, "126")
        evaluate(body)
        rows = link_rows(env)
        assert [r["variation_id"] for r in rows] == [175550253195, 175550253196, 175550253197, 175550253198]
        assert {r["producto_item_id"] for r in rows} == {7}

    def test_two_publications_of_one_sku_link_to_the_same_product(self, env) -> None:
        add_product(env, 41, SKU_A)
        evaluate(sample_item("MLA874027718"))
        evaluate(sample_item(ITEM))
        assert [(r["item_id"], r["producto_item_id"]) for r in link_rows(env)] == [
            ("MLA874027718", 41),
            (ITEM, 41),
        ]

    def test_the_model_covers_exactly_the_columns_of_the_migration(self, env) -> None:
        with env.connect() as conn:
            columns = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'ml_item_product_links'"
                    )
                )
            }
        assert columns == {c.name for c in MlItemProductLink.__table__.columns}


class TestAutomaticChanges:
    def test_a_unit_whose_sku_now_matches_another_product_moves_and_is_logged_atomically(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        evaluate(sample_item(ITEM), minutes=1, events=True)
        add_product(events_on, 42, SKU_B)
        changed = sample_item(ITEM)
        changed["attributes"] = [
            {**a, "value_name": SKU_B} if a["id"] == "SELLER_SKU" else a for a in changed["attributes"]
        ]  # real payload, one value changed

        result = evaluate(changed, minutes=5, events=True)

        assert result.changed == 1
        row = link(events_on)
        assert (row["producto_item_id"], row["matched_sku"], row["linked_at"]) == (42, SKU_B, at(5))
        (entry,) = log_rows(events_on)
        assert (entry["entity_id"], entry["item_id"], entry["kind"]) == (f"{ITEM}:0", ITEM, "change")
        assert entry["observed_at"] == at(5)
        assert entry["changed_paths"] == ["producto_item_id", "matched_sku"]
        assert entry["changes"] == [
            {"p": "producto_item_id", "op": "replace", "old": 41, "new": 42},
            {"p": "matched_sku", "op": "replace", "old": SKU_A, "new": SKU_B},
        ]
        typed = map_item(changed)
        assert entry["context"] == {
            "variation_id": 0,
            "producto_item_id_old": 41,
            "producto_item_id_new": 42,
            "source_old": "sku_auto",
            "source_new": "sku_auto",
            "match_status_old": "linked",
            "match_status_new": "linked",
            "matched_sku": SKU_B,
            "sku_field": "seller_sku_attr",
            "linked_by": None,
            "official_store_id": typed["official_store_id"],
            "brand": typed["brand"],
        }
        (event,) = event_rows(events_on)
        assert event["event_type"] == "product_link_changed"
        assert (event["item_id"], event["old_value"], event["new_value"]) == (ITEM, 41, 42)
        assert event["change_log_id"] == entry["id"]

    def test_without_the_events_flag_the_change_is_logged_but_no_event_is_written(self, env) -> None:
        add_product(env, 41, SKU_A)
        evaluate(sample_item(ITEM), minutes=1)
        add_product(env, 42, SKU_B)
        evaluate(_with_sku(SKU_B), minutes=5, events=False)
        assert len(log_rows(env)) == 1 and event_rows(env) == []

    def test_a_failure_writing_the_event_rolls_back_the_link_change_and_its_log_row(
        self, events_on, monkeypatch
    ) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, SKU_B)
        evaluate(sample_item(ITEM), minutes=1, events=True)

        def boom(db, entry):
            raise RuntimeError("event insert failed")

        monkeypatch.setattr(events_store, "write_events", boom)
        with pytest.raises(RuntimeError):
            evaluate(_with_sku(SKU_B), minutes=5, events=True)

        assert link(events_on)["producto_item_id"] == 41
        assert log_rows(events_on) == []

    def test_a_unit_that_stops_matching_becomes_unmatched_and_is_logged(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        evaluate(sample_item(ITEM), minutes=1, events=True)
        remove_product(events_on, 41)

        evaluate(sample_item(ITEM), minutes=5, events=True, force=True)

        row = link(events_on)
        assert (row["match_status"], row["producto_item_id"]) == ("unmatched", None)
        (entry,) = log_rows(events_on)
        assert entry["context"]["match_status_old"] == "linked"
        assert entry["context"]["match_status_new"] == "unmatched"
        (event,) = event_rows(events_on)
        assert (event["old_value"], event["new_value"]) == (41, None)

    def test_unchanged_sku_and_catalog_only_move_the_evaluation_timestamp(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        evaluate(sample_item(ITEM), minutes=1, events=True)
        before = link(events_on)

        result = evaluate(sample_item(ITEM), minutes=9, events=True, force=True)

        after = link(events_on)
        assert result.changed == 0 and result.unchanged == 1
        assert after["evaluated_at"] == at(9)
        assert {k: v for k, v in after.items() if k != "evaluated_at"} == {
            k: v for k, v in before.items() if k != "evaluated_at"
        }
        assert log_rows(events_on) == [] and event_rows(events_on) == []

    def test_an_item_whose_keys_were_all_evaluated_is_skipped_without_reading_the_catalog(
        self, env, monkeypatch
    ) -> None:
        add_product(env, 41, SKU_A)
        evaluate(sample_item(ITEM), minutes=1)

        def forbidden(db, keys):
            raise AssertionError("the catalog must not be read for an up-to-date item")

        monkeypatch.setattr(links, "load_codigo_index", forbidden)
        result = evaluate(sample_item(ITEM), minutes=9)

        assert result.skipped == 1 and link(env)["evaluated_at"] == at(1)

    def test_a_new_catalog_product_links_an_unmatched_unit_on_a_forced_evaluation(self, events_on) -> None:
        evaluate(sample_item(ITEM), minutes=1, events=True)
        add_product(events_on, 41, SKU_A)

        evaluate(sample_item(ITEM), minutes=5, events=True, force=True)

        assert link(events_on)["producto_item_id"] == 41
        (entry,) = log_rows(events_on)
        assert entry["context"]["match_status_old"] == "unmatched"


class TestManualAlwaysWins:
    def test_a_manual_link_stays_when_the_sku_points_to_another_product(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, SKU_B)
        put_link(events_on, ITEM, 0, "manual", "linked", 41, linked_by=3, note="by hand", evaluated_sku_key=SKU_A)

        result = evaluate(_with_sku(SKU_B), minutes=5, events=True)

        row = link(events_on)
        assert (row["source"], row["producto_item_id"], row["linked_by"], row["note"]) == ("manual", 41, 3, "by hand")
        assert row["linked_at"] == at(-60)
        assert (row["suggestion_status"], row["suggested_producto_item_id"]) == ("linked", 42)
        assert row["evaluated_sku_key"] == SKU_B
        assert log_rows(events_on) == [] and event_rows(events_on) == []
        assert result.manual_differs == 1 and result.changed == 0

    def test_a_manual_link_that_agrees_with_the_suggestion_is_not_a_divergence(self, env) -> None:
        add_product(env, 41, SKU_A)
        put_link(env, ITEM, 0, "manual", "linked", 41)
        assert evaluate(sample_item(ITEM)).manual_differs == 0

    def test_manual_none_stays_no_product_even_when_the_sku_matches(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        put_link(events_on, ITEM, 0, "manual_none", "no_product", None)

        result = evaluate(sample_item(ITEM), minutes=5, events=True)

        row = link(events_on)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("manual_none", "no_product", None)
        assert (row["suggestion_status"], row["suggested_producto_item_id"]) == ("linked", 41)
        assert result.manual_differs == 1
        assert log_rows(events_on) == []

    def test_a_forced_evaluation_never_changes_a_manual_link(self, env) -> None:
        put_link(env, ITEM, 0, "manual", "linked", 41)
        add_product(env, 42, SKU_A)
        evaluate(sample_item(ITEM), force=True)
        assert link(env)["producto_item_id"] == 41


class TestProductLinkChangedIsRederivable:
    def test_the_event_is_rebuilt_from_the_change_log_row_alone(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, SKU_B)
        evaluate(sample_item(ITEM), minutes=1, events=True)
        evaluate(_with_sku(SKU_B), minutes=5, events=True)
        (original,) = event_rows(events_on)
        with events_on.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_events"))

        with database.get_background_db() as db:
            created = events_store.rederive_events(db, item_id=ITEM)

        (rebuilt,) = event_rows(events_on)
        assert created == 1
        assert bytes(rebuilt["dedupe_key"]) == bytes(original["dedupe_key"])
        assert (rebuilt["event_type"], rebuilt["old_value"], rebuilt["new_value"]) == ("product_link_changed", 41, 42)
        assert rebuilt["payload"] == original["payload"]


def _with_sku(sku: str) -> dict:
    """Real MLA882393030 with its SELLER_SKU value changed (one field)."""
    body = sample_item(ITEM)
    body["attributes"] = [{**a, "value_name": sku} if a["id"] == "SELLER_SKU" else a for a in body["attributes"]]
    return body


# --- the apply_fetch hook (design D20, step 7) ---------------------------------------------------


@pytest.fixture()
def links_on(events_on):
    set_setting("links.enabled", True, "test")
    return events_on


class TestApplyFetchHook:
    def test_the_first_sighting_creates_the_link_in_the_same_transaction(self, links_on) -> None:
        add_product(links_on, 41, SKU_A)

        outcome = apply(sample_item(ITEM), ITEM, minutes=1)

        assert outcome.kind == "first_seen"
        row = link(links_on)
        assert (row["source"], row["producto_item_id"], row["evaluated_at"]) == ("sku_auto", 41, at(1))
        assert log_rows(links_on) == []

    def test_a_refresh_that_changes_the_seller_sku_relinks_in_the_same_transaction(self, links_on) -> None:
        add_product(links_on, 41, SKU_A)
        add_product(links_on, 42, SKU_B)
        apply(sample_item(ITEM), ITEM, minutes=1)

        outcome = apply(_with_sku(SKU_B), ITEM, minutes=5)

        assert outcome.kind == "changed"
        assert link(links_on)["producto_item_id"] == 42
        (entry,) = log_rows(links_on)
        assert entry["entity_id"] == f"{ITEM}:0"
        (event_row,) = event_rows(links_on)
        assert event_row["event_type"] == "product_link_changed"

    def test_a_refresh_without_a_sku_change_does_not_touch_the_links(self, links_on) -> None:
        add_product(links_on, 41, SKU_A)
        body = sample_item(ITEM)
        apply(body, ITEM, minutes=1)
        before = link(links_on)
        body["title"] = body["title"] + "!"  # real payload, one field changed

        apply(body, ITEM, minutes=5)

        assert link(links_on) == before

    def test_with_links_off_no_link_is_written_and_the_catalog_is_never_read(self, events_on) -> None:
        statements: list[str] = []

        def record(conn, cursor, statement, *rest):
            statements.append(statement)

        event.listen(events_on, "before_cursor_execute", record)
        try:
            apply(sample_item(ITEM), ITEM, minutes=1)
        finally:
            event.remove(events_on, "before_cursor_execute", record)

        assert statements  # the listener really saw the fetch
        assert not [sql for sql in statements if "productos_erp" in sql or "ml_item_product_links" in sql]
        assert link_rows(events_on) == []

    def test_a_links_failure_never_blocks_the_item_and_leaves_the_unit_for_the_sweep(
        self, links_on, monkeypatch
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("catalog unreadable")

        monkeypatch.setattr(links, "evaluate_item", boom)

        outcome = apply(sample_item(ITEM), ITEM, minutes=1)

        assert outcome.kind == "first_seen"
        assert item_row(links_on, ITEM)["raw"] is not None
        assert link_rows(links_on) == []

    def test_the_flag_can_be_passed_by_the_caller_without_reading_settings(self, links_on, monkeypatch) -> None:
        monkeypatch.setattr(store_module, "_links_enabled", lambda: pytest.fail("flag read although passed"))
        add_product(links_on, 41, SKU_A)
        apply(sample_item(ITEM), ITEM, minutes=1, links_enabled=True, events_enabled=True)
        assert link(links_on)["producto_item_id"] == 41

    def test_an_unreadable_flag_means_no_links(self, links_on, monkeypatch) -> None:
        from app.services.ml_publications import settings_store

        def broken(handler):
            raise RuntimeError("settings down")

        monkeypatch.setattr(settings_store, "is_enabled", broken)
        apply(sample_item(ITEM), ITEM, minutes=1, events_enabled=False)
        assert link_rows(links_on) == []

    def test_a_negative_state_body_evaluates_nothing(self, links_on) -> None:
        apply(sample_item(ITEM), ITEM, minutes=1)
        only_not_found(ITEM, 5)
        assert [r["item_id"] for r in link_rows(links_on)] == [ITEM]


# --- coverage report (spec "Coverage report") -----------------------------------------------------

VARIATIONS = "MLA1207279308"  # real closed item with 4 variations and no SKU anywhere
SAMPLE_ITEMS = {"MLA874027718", "MLA882393030", "MLA862580589", VARIATIONS}


def store_item(item_id: str, minutes: float = 0) -> dict:
    """Write a real capture to the store with linking OFF; returns its body."""
    if item_id == VARIATIONS:
        body = item_with_variations()
    elif item_id in SAMPLE_ITEMS:
        body = sample_item(item_id)
    else:
        body = bulk_item(item_id)
    apply(body, item_id, minutes=minutes, links_enabled=False, events_enabled=False)
    return body


def coverage_of(engine, **kwargs) -> dict:
    with database.get_background_db() as db:
        return links.coverage(db, **kwargs)


@pytest.fixture()
def coverage_data(env):
    """Nine units, one or two per class (see `test_every_unit_lands_in_exactly_one_primary_class`)."""
    add_product(env, 41, SKU_A)
    add_product(env, 7, "OTHER")
    add_product(env, 61, "840006604815")
    add_product(env, 62, "840006604815")  # two products share the codigo of MLA934406852
    for minutes, item_id in enumerate(
        ["MLA874027718", "MLA882393030", PAUSED_ITEM, "MLA934406852", "MLA862580589", VARIATIONS], start=1
    ):
        body = store_item(item_id, minutes)
        if item_id in ("MLA874027718", "MLA934406852", VARIATIONS):
            evaluate(body, minutes=minutes)
    put_link(env, "MLA882393030", 0, "manual", "linked", 7, linked_by=3)  # suggestion (41) differs
    evaluate(sample_item("MLA882393030"), minutes=9)
    put_link(env, PAUSED_ITEM, 0, "manual_none", "no_product", None, evaluated_at=at(9))
    with env.begin() as conn:
        conn.execute(
            text(
                "UPDATE ml_item_product_links SET source='sku_auto', match_status='linked', producto_item_id=999 "
                "WHERE item_id = :i AND variation_id = 175550253195"
            ),
            {"i": VARIATIONS},
        )
        conn.execute(
            text(
                "UPDATE ml_item_product_links SET matched_sku='XYZ' WHERE item_id = :i AND variation_id = 175550253197"
            ),
            {"i": VARIATIONS},
        )
        conn.execute(
            text("DELETE FROM ml_item_product_links WHERE item_id = :i AND variation_id = 175550253198"),
            {"i": VARIATIONS},
        )
    return env


PAUSED_ITEM = "MLA935110613"


class TestCoverage:
    def test_every_unit_lands_in_exactly_one_primary_class_and_the_counts_sum_to_the_total(self, coverage_data) -> None:
        report = coverage_of(coverage_data)

        assert report["total_units"] == 9
        assert report["classes"] == {
            "linked_auto": 1,
            "linked_manual": 1,
            "manual_none": 1,
            "unmatched_no_key": 1,
            "unmatched_key_not_found": 1,
            "conflict": 1,
            "dangling": 1,
            "never_evaluated": 2,
        }
        assert sum(report["classes"].values()) == report["total_units"]

    def test_manual_differs_is_reported_beside_the_primary_classes(self, coverage_data) -> None:
        assert coverage_of(coverage_data)["manual_differs"] == 1

    def test_counts_are_split_by_item_status_and_by_item_level_versus_variation_units(self, coverage_data) -> None:
        report = coverage_of(coverage_data)
        by_status = report["by_status"]

        total = sum(sum(counts.values()) for status in by_status.values() for counts in status.values())
        assert total == 9
        closed = by_status[item_row(coverage_data, VARIATIONS)["status"]]
        assert sum(closed["variation"].values()) == 4 and closed["item_level"] == {}
        assert by_status[item_row(coverage_data, PAUSED_ITEM)["status"]]["item_level"].get("manual_none") == 1

    def test_samples_are_bounded_per_class(self, coverage_data) -> None:
        report = coverage_of(coverage_data, sample_size=1)
        assert all(len(ids) <= 1 for ids in report["samples"].values())
        assert report["samples"]["never_evaluated"] == [{"item_id": VARIATIONS, "variation_id": 175550253198}]
        assert report["samples"]["dangling"] == [{"item_id": VARIATIONS, "variation_id": 175550253195}]

    def test_a_manual_link_to_a_product_that_no_longer_exists_is_dangling_not_linked_manual(self, env) -> None:
        store_item(PAUSED_ITEM, 1)
        put_link(env, PAUSED_ITEM, 0, "manual", "linked", 555, evaluated_at=at(1))
        report = coverage_of(env)
        assert report["classes"]["dangling"] == 1 and report["classes"]["linked_manual"] == 0

    def test_an_empty_store_reports_zero_everywhere(self, env) -> None:
        report = coverage_of(env)
        assert report["total_units"] == 0
        assert set(report["classes"].values()) == {0}
        assert report["by_status"] == {} and report["manual_differs"] == 0
        assert all(ids == [] for ids in report["samples"].values())

    def test_it_is_read_only(self, coverage_data) -> None:
        before = (link_rows(coverage_data), log_rows(coverage_data))
        coverage_of(coverage_data)
        assert (link_rows(coverage_data), log_rows(coverage_data)) == before
