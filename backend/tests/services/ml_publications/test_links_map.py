"""Map-first product links against a real Postgres (publicaciones-ml-vinculo-mapa V1).

An automatic unit links first to the product the ERP publication map (`publicaciones_ml`, the map the
Productos screen uses) names for its publication; the SKU rule only decides the publications the map does
not know. The SKU result is always kept as the unit's suggestion. Items are real captures;
`productos_erp` and `publicaciones_ml` rows are plain test data (our own tables, not ML payloads).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import event, text

from app.core import database
from app.services.ml_publications import links
from app.services.ml_publications.mappers import map_item, map_variations
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import item_with_variations, sample_item
from tests.services.ml_publications.test_links_store import (
    ITEM,
    SKU_A,
    T0,
    _with_sku,
    add_product,
    at,
    evaluate,
    link,
    log_rows,
    put_link,
)
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres

OTHER_ITEM = "MLA874027718"  # real item sharing SELLER_SKU SKU_A with ITEM
VARIATIONS_ITEM = "MLA1207279308"  # real item with 4 variations


def add_map(engine, mla: str, product: int, *, activo: bool = True) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO publicaciones_ml (mla, item_id, activo) VALUES (:m, :p, :a)"),
            {"m": mla, "p": product, "a": activo},
        )


def update_map(engine, mla: str, **values) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE publicaciones_ml SET {assignments} WHERE mla = :mla"), {"mla": mla, **values})


def suggestion_of(row) -> tuple:
    return row["suggestion_status"], row["suggested_producto_item_id"], row["suggestion_candidates"]


def fingerprint() -> str:
    with database.get_background_db() as db:
        return links.catalog_fingerprint(db)


class TestMapFirst:
    def test_the_map_beats_a_sku_that_names_another_product(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, ITEM, 42)

        evaluate(sample_item(ITEM), minutes=1)

        row = link(env)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "linked", 42)
        assert (row["matched_sku"], row["sku_field"], row["candidate_ids"]) == (SKU_A, "seller_sku_attr", None)
        assert suggestion_of(row) == ("linked", 41, 1)  # the SKU rule's answer is kept for the divergence view

    def test_the_map_links_a_publication_whose_sku_is_the_placeholder_zero(self, env) -> None:
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, ITEM, 42)

        evaluate(_with_sku("0"), minutes=1)

        row = link(env)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "linked", 42)
        assert row["matched_sku"] == "0"
        assert suggestion_of(row) == ("unmatched", None, 0)

    def test_the_map_decides_a_sku_conflict(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 43, SKU_A)
        add_map(env, ITEM, 43)

        evaluate(sample_item(ITEM), minutes=1)

        row = link(env)
        assert (row["match_status"], row["producto_item_id"], row["candidate_ids"]) == ("linked", 43, None)
        assert suggestion_of(row) == ("conflict", None, 2)

    def test_an_inactive_map_row_is_ignored(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, ITEM, 42, activo=False)

        evaluate(sample_item(ITEM), minutes=1)

        row = link(env)
        assert (row["match_status"], row["producto_item_id"]) == ("linked", 41)
        assert suggestion_of(row) == ("linked", 41, 1)

    def test_a_map_product_missing_from_the_catalog_falls_back_to_the_sku(self, env) -> None:
        add_product(env, 41, SKU_A)
        with env.begin() as conn:  # production's map may name a product the catalog no longer has
            conn.execute(text("ALTER TABLE publicaciones_ml DROP CONSTRAINT publicaciones_ml_item_id_fkey"))
        add_map(env, ITEM, 99)

        evaluate(sample_item(ITEM), minutes=1)

        row = link(env)
        assert (row["match_status"], row["producto_item_id"]) == ("linked", 41)

    def test_the_map_of_another_publication_does_not_leak(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, OTHER_ITEM, 42)

        evaluate(sample_item(ITEM), minutes=1)

        assert link(env)["producto_item_id"] == 41

    def test_every_variation_unit_of_a_mapped_publication_links_to_the_map_product(self, env) -> None:
        body = item_with_variations()
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, VARIATIONS_ITEM, 42)
        typed = map_item(body)

        with database.get_background_db() as db:
            links.evaluate_item(db, VARIATIONS_ITEM, typed, map_variations(body), now=at(1), events_enabled=False)

        with env.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT variation_id, producto_item_id, match_status FROM ml_item_product_links WHERE item_id = :i"
                ),
                {"i": VARIATIONS_ITEM},
            ).all()
        assert len(rows) == 4
        assert {(product, status) for _, product, status in rows} == {(42, "linked")}
        assert all(variation_id > 0 for variation_id, _, _ in rows)

    def test_a_move_to_the_map_product_is_logged_with_the_erp_map_rule(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-PRODUCT")
        evaluate(sample_item(ITEM), minutes=1, events=True)
        add_map(events_on, ITEM, 42)

        result = evaluate(sample_item(ITEM), minutes=2, events=True, force=True)

        assert result.changed == 1
        (entry,) = log_rows(events_on)
        assert (entry["context"]["producto_item_id_old"], entry["context"]["producto_item_id_new"]) == (41, 42)
        assert entry["context"]["match_rule"] == "erp_map"
        assert suggestion_of(link(events_on)) == ("linked", 41, 1)

    def test_a_deactivated_map_row_hands_the_unit_back_to_the_sku(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-PRODUCT")
        add_map(events_on, ITEM, 42)
        evaluate(sample_item(ITEM), minutes=1, events=True)
        update_map(events_on, ITEM, activo=False)

        evaluate(sample_item(ITEM), minutes=2, events=True, force=True)

        assert link(events_on)["producto_item_id"] == 41
        (entry,) = log_rows(events_on)
        assert entry["context"]["match_rule"] == "codigo"


class TestManualStillWins:
    def test_a_manual_link_is_never_moved_by_the_map(self, env) -> None:
        add_product(env, 7, "MANUAL-PICK")
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        put_link(env, ITEM, 0, "manual", "linked", 7, linked_by=3, evaluated_sku_key="x", evaluated_at=at(-60))
        add_map(env, ITEM, 42)

        result = evaluate(sample_item(ITEM), minutes=1, force=True)

        row = link(env)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("manual", "linked", 7)
        assert suggestion_of(row) == ("linked", 41, 1)  # still the SKU rule's answer
        assert result.manual_differs == 1  # measured against the SKU suggestion, as before
        assert log_rows(env) == []

    def test_manual_none_is_never_moved_by_the_map(self, env) -> None:
        add_product(env, 42, "MAP-PRODUCT")
        put_link(env, ITEM, 0, "manual_none", "no_product", None, evaluated_sku_key="x", evaluated_at=at(-60))
        add_map(env, ITEM, 42)

        result = evaluate(sample_item(ITEM), minutes=1, force=True)

        row = link(env)
        assert (row["source"], row["producto_item_id"]) == ("manual_none", None)
        assert result.manual_differs == 0  # the SKU matches nothing: no divergence


class TestSingleItemPaths:
    def test_the_fetch_links_by_the_map(self, events_on) -> None:
        set_setting("links.enabled", True, "test")
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-PRODUCT")
        add_map(events_on, ITEM, 42)

        apply(sample_item(ITEM), ITEM, minutes=1)

        row = link(events_on)
        assert (row["producto_item_id"], suggestion_of(row)) == (42, ("linked", 41, 1))

    def test_revert_to_auto_applies_the_map(self, events_on) -> None:
        add_product(events_on, 7, "MANUAL-PICK")
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-PRODUCT")
        add_map(events_on, ITEM, 42)
        apply(sample_item(ITEM), ITEM, minutes=1)
        put_link(events_on, ITEM, 0, "manual", "linked", 7, linked_by=3, evaluated_sku_key=SKU_A, evaluated_at=at(1))
        with events_on.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE auditoria (id serial PRIMARY KEY, item_id integer, usuario_id integer NOT NULL, "
                    "tipo_accion varchar(50) NOT NULL, valores_anteriores json, valores_nuevos json, es_masivo integer, "
                    "productos_afectados integer, comentario varchar(500), fecha timestamp NOT NULL)"
                )
            )

        with database.get_background_db() as db:
            assert links.revert_to_auto(db, ITEM, 0, 17, now=at(5), events_enabled=True).changed

        row = link(events_on)
        assert (row["source"], row["producto_item_id"], suggestion_of(row)) == ("sku_auto", 42, ("linked", 41, 1))
        assert max(log_rows(events_on), key=lambda e: e["id"])["context"]["match_rule"] == "erp_map"


class TestSweep:
    def test_the_sweep_reads_the_map_once_per_evaluated_item_never_per_unit(self, events_on) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-PRODUCT")
        add_map(events_on, ITEM, 42)
        add_map(events_on, VARIATIONS_ITEM, 42)
        apply(sample_item(ITEM), ITEM, minutes=1)  # links off: the sweep links them
        apply(sample_item(OTHER_ITEM), OTHER_ITEM, minutes=1)
        apply(item_with_variations(), VARIATIONS_ITEM, minutes=1)  # 4 variation units, one map read
        statements: list[str] = []

        def capture(conn, cursor, statement, *args) -> None:
            if "publicaciones_ml" in statement and "md5" not in statement:  # the fingerprint is counted apart
                statements.append(statement)

        event.listen(events_on, "before_cursor_execute", capture)
        try:
            result = links.run_sweep(deadline=T0 + timedelta(hours=1), gate=lambda: False, now=lambda: T0)
        finally:
            event.remove(events_on, "before_cursor_execute", capture)

        assert result.complete and result.units.created == 6
        assert len(statements) == 3
        assert link(events_on, ITEM)["producto_item_id"] == 42
        assert link(events_on, OTHER_ITEM)["producto_item_id"] == 41

    def test_a_map_change_after_the_batch_snapshot_is_read_under_the_item_lock(self, events_on, monkeypatch) -> None:
        add_product(events_on, 41, SKU_A)
        add_product(events_on, 42, "MAP-A")
        add_product(events_on, 43, "MAP-B")
        add_map(events_on, ITEM, 42)
        apply(sample_item(ITEM), ITEM, minutes=1)
        links.run_sweep(deadline=T0 + timedelta(hours=1), gate=lambda: False, now=lambda: T0)
        assert link(events_on)["producto_item_id"] == 42
        add_product(events_on, 44, "UNRELATED")  # a catalog change: the next lap is forced
        evaluate_one = links._evaluate_one

        def map_moves_to_b_after_the_snapshot(item_id, **kwargs):
            update_map(events_on, ITEM, item_id=43)  # committed between the batch snapshot and the item's lock
            return evaluate_one(item_id, **kwargs)

        monkeypatch.setattr(links, "_evaluate_one", map_moves_to_b_after_the_snapshot)

        result = links.run_sweep(deadline=T0 + timedelta(hours=1), gate=lambda: False, now=lambda: T0)

        assert result.forced
        assert link(events_on)["producto_item_id"] == 43
        assert [e["context"]["producto_item_id_new"] for e in log_rows(events_on)] == [43]  # no flap back to A


class TestFingerprint:
    def test_it_changes_when_a_map_row_is_added_repointed_or_deactivated(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        seen = [fingerprint()]

        add_map(env, ITEM, 41)
        seen.append(fingerprint())
        update_map(env, ITEM, item_id=42)
        seen.append(fingerprint())
        update_map(env, ITEM, activo=False)
        seen.append(fingerprint())

        assert len(set(seen)) == 4

    def test_it_is_stable_while_nothing_changes(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_map(env, ITEM, 41)

        assert fingerprint() == fingerprint()

    def test_a_map_change_alone_forces_the_next_lap(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        apply(sample_item(ITEM), ITEM, minutes=1)
        links.run_sweep(deadline=T0 + timedelta(hours=1), gate=lambda: False, now=lambda: T0)
        assert link(env)["producto_item_id"] == 41
        add_map(env, ITEM, 42)

        result = links.run_sweep(deadline=T0 + timedelta(hours=1), gate=lambda: False, now=lambda: T0)

        assert result.forced and result.units.changed == 1
        assert link(env)["producto_item_id"] == 42


def divergent() -> list[tuple[str, int]]:
    with database.get_background_db() as db:
        page = links.list_units(db, "sku_divergent")
    return [(i["item_id"], i["variation_id"]) for i in page["items"]]


class TestSkuDivergence:
    """The units whose seller SKU disagrees with the product the map links them to (V2).

    Evaluated through the real rule: an automatic unit the SKU links by itself always stores the same product as
    link and suggestion, so only a map-linked unit can diverge.
    """

    def test_a_sku_naming_another_product_than_the_map_diverges(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, ITEM, 42)

        evaluate(sample_item(ITEM), minutes=1)

        assert divergent() == [(ITEM, 0)]

    def test_a_sku_matching_nothing_while_the_map_links_diverges(self, env) -> None:
        add_product(env, 42, "MAP-PRODUCT")
        add_map(env, ITEM, 42)

        evaluate(_with_sku("NOT-A-PRODUCT"), minutes=1)

        assert divergent() == [(ITEM, 0)]

    def test_a_sku_conflict_while_the_map_links_diverges(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_product(env, 43, SKU_A)
        add_map(env, ITEM, 43)

        evaluate(sample_item(ITEM), minutes=1)

        assert divergent() == [(ITEM, 0)]

    def test_a_sku_agreeing_with_the_map_does_not_diverge(self, env) -> None:
        add_product(env, 41, SKU_A)
        add_map(env, ITEM, 41)

        evaluate(sample_item(ITEM), minutes=1)

        assert divergent() == []

    @pytest.mark.parametrize("sku", [SKU_A, "NOT-A-PRODUCT"])
    def test_a_unit_the_map_does_not_know_never_diverges(self, env, sku) -> None:
        add_product(env, 41, SKU_A)

        evaluate(_with_sku(sku), minutes=1)

        assert divergent() == []

    def test_manual_links_are_out_of_the_divergence(self, env) -> None:
        add_product(env, 41, SKU_A)
        put_link(
            env,
            ITEM,
            0,
            "manual",
            "linked",
            41,
            suggestion_status="unmatched",
            evaluated_at=at(1),
        )
        put_link(
            env,
            OTHER_ITEM,
            0,
            "manual",
            "linked",
            41,
            suggestion_status="linked",
            suggested_producto_item_id=5,
            evaluated_at=at(1),
        )

        assert divergent() == []
