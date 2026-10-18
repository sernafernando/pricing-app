"""One-time seed of manual product links from the ERP publication map, against a real Postgres.

Items are real captures stored through `apply_fetch` (links off); link rows, `productos_erp` and the ERP
map `tb_mercadolibre_items_publicados` (`mlp_publicationid` -> `item_id`) are plain test data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import database
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.scripts import seed_vinculos_ml_desde_erp as seed
from app.services.ml_publications import links
from tests.services.ml_publications.conftest import item_with_variations, sample_item
from tests.services.ml_publications.test_links_store import (
    ITEM,
    SKU_A,
    _with_sku,
    add_product,
    at,
    link,
    log_rows,
    put_link,
)
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres

OTHER = "MLA874027718"  # real capture sharing SKU_A with ITEM
VARIATIONS = "MLA1207279308"


@pytest.fixture()
def erp(env):
    MercadoLibreItemPublicado.__table__.create(bind=env)
    return env


def erp_map(engine, publication: str, product: int | None, mlp_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, item_id, mlp_publicationid) VALUES (:m, :i, :p)"
            ),
            {"m": mlp_id, "i": product, "p": publication},
        )


def unmatched(engine, item_id: str = ITEM, sku: str = SKU_A, status: str = "unmatched") -> None:
    put_link(engine, item_id, 0, "sku_auto", status, None, matched_sku=sku, evaluated_sku_key=sku, evaluated_at=at(-60))


def run(apply_: bool) -> seed.SeedCounts:
    return seed.run(apply=apply_, now=lambda: at(10))


class TestSeed:
    def test_dry_run_counts_and_writes_nothing(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "OTHER-CODE")
        erp_map(erp, ITEM, 41, 1)

        counts = run(False)

        assert (counts.candidates, counts.seeded) == (1, 1)
        row = link(erp)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "unmatched", None)
        assert log_rows(erp) == []

    def test_apply_writes_a_marked_manual_link_with_history(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "OTHER-CODE")
        erp_map(erp, ITEM, 41, 1)

        counts = run(True)

        assert counts.seeded == 1
        row = link(erp)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("manual", "linked", 41)
        assert (row["note"], row["linked_by"], row["linked_at"]) == (seed.SEED_NOTE, None, at(10))
        (entry,) = log_rows(erp)
        assert entry["context"]["source_new"] == "manual" and entry["context"]["match_rule"] == "erp_seed"

    def test_a_second_apply_changes_nothing(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "OTHER-CODE")
        erp_map(erp, ITEM, 41, 1)
        run(True)

        counts = run(True)

        assert (counts.candidates, counts.seeded) == (0, 0)
        assert len(log_rows(erp)) == 1

    def test_a_conflict_is_settled_by_the_erp_map(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        add_product(erp, 41, SKU_A)
        add_product(erp, 42, SKU_A)
        unmatched(erp, status="conflict")
        erp_map(erp, ITEM, 42, 1)

        assert run(True).seeded == 1
        assert (link(erp)["source"], link(erp)["producto_item_id"]) == ("manual", 42)

    def test_decisions_and_auto_links_are_never_touched(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        apply(sample_item(OTHER), OTHER)
        add_product(erp, 41, SKU_A)
        add_product(erp, 50, "OTHER-CODE")
        put_link(erp, ITEM, 0, "manual_none", "no_product", None, evaluated_sku_key=SKU_A, evaluated_at=at(-60))
        put_link(
            erp, OTHER, 0, "sku_auto", "linked", 41, matched_sku=SKU_A, evaluated_sku_key=SKU_A, evaluated_at=at(-60)
        )
        erp_map(erp, ITEM, 50, 1)
        erp_map(erp, OTHER, 50, 2)

        counts = run(True)

        assert (counts.candidates, counts.seeded) == (0, 0)
        assert (link(erp)["source"], link(erp)["producto_item_id"]) == ("manual_none", None)
        assert (link(erp, OTHER)["source"], link(erp, OTHER)["producto_item_id"]) == ("sku_auto", 41)

    def test_skips_missing_map_ambiguous_map_and_products_gone_from_the_catalog(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        apply(sample_item(OTHER), OTHER)
        unmatched(erp)
        unmatched(erp, OTHER)
        add_product(erp, 41, "X")
        erp_map(erp, ITEM, 41, 1)
        erp_map(erp, ITEM, 43, 2)  # two products for one publication: ambiguous
        erp_map(erp, OTHER, 99, 3)  # product 99 is not in productos_erp

        counts = run(True)

        assert (counts.candidates, counts.seeded, counts.ambiguous, counts.product_missing) == (2, 0, 1, 1)
        assert link(erp)["source"] == link(erp, OTHER)["source"] == "sku_auto"

    def test_a_publication_absent_from_the_map_is_counted(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        assert run(True).not_in_erp == 1

    def test_a_unit_the_automatic_rule_now_links_is_left_to_it(self, erp) -> None:
        apply(_with_sku("3075"), ITEM)
        unmatched(erp, sku="3075")
        add_product(erp, 3075, "OTHER")
        add_product(erp, 41, "X")
        erp_map(erp, ITEM, 41, 1)

        counts = run(True)

        assert (counts.relinked_auto, counts.seeded) == (1, 0)
        assert (link(erp)["source"], link(erp)["producto_item_id"]) == ("sku_auto", 3075)

    def test_items_with_variations_are_not_candidates(self, erp) -> None:
        apply(item_with_variations(), VARIATIONS)
        unmatched(erp, VARIATIONS)
        add_product(erp, 41, "X")
        erp_map(erp, VARIATIONS, 41, 1)
        assert run(True).candidates == 0


class TestCli:
    def test_dry_run_is_the_default(self, erp, capsys) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "X")
        erp_map(erp, ITEM, 41, 1)

        assert seed.main([]) == 0

        assert "DRY-RUN" in capsys.readouterr().out
        assert link(erp)["source"] == "sku_auto"


class _PgError(Exception):
    """Stand-in for a driver error: the seed only reads its SQLSTATE (`pgcode`)."""

    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


def two_mapped_candidates(engine) -> None:
    """OTHER sorts before ITEM, so OTHER is processed first."""
    apply(sample_item(ITEM), ITEM)
    apply(sample_item(OTHER), OTHER)
    unmatched(engine)
    unmatched(engine, OTHER)
    add_product(engine, 41, "X")
    add_product(engine, 42, "Y")
    erp_map(engine, ITEM, 41, 1)
    erp_map(engine, OTHER, 42, 2)


def failing_on(monkeypatch, item_id: str, error: Exception):
    """Make the seed fail on one item; returns the real function to put back."""
    real = links.seed_manual_link

    def seed_or_fail(db, target, *args, **kwargs):
        if target == item_id:
            raise error
        return real(db, target, *args, **kwargs)

    monkeypatch.setattr(links, "seed_manual_link", seed_or_fail)
    return real


class TestFailurePaths:
    def test_an_item_gone_meanwhile_is_counted_as_changed_and_the_batch_continues(self, erp, monkeypatch) -> None:
        two_mapped_candidates(erp)
        failing_on(monkeypatch, OTHER, links.UnknownItem(OTHER))

        counts = run(True)

        assert (counts.candidates, counts.changed, counts.seeded) == (2, 1, 1)
        assert link(erp, OTHER)["source"] == "sku_auto"
        assert (link(erp)["source"], link(erp)["producto_item_id"]) == ("manual", 41)

    def test_a_locked_unit_is_counted_as_busy_and_the_batch_continues(self, erp, monkeypatch) -> None:
        two_mapped_candidates(erp)
        monkeypatch.setattr(seed, "LOCK_TIMEOUT", "100ms")
        with erp.connect() as holder:  # another writer holds OTHER's link row: a real lock_timeout (55P03)
            holder.execute(text("SELECT 1 FROM ml_item_product_links WHERE item_id = :i FOR UPDATE"), {"i": OTHER})
            counts = run(True)
            holder.rollback()

        assert (counts.candidates, counts.busy, counts.seeded) == (2, 1, 1)
        assert link(erp, OTHER)["source"] == "sku_auto"
        assert link(erp)["source"] == "manual"

    def test_any_other_database_error_stops_the_run_and_a_rerun_resumes(self, erp, monkeypatch) -> None:
        two_mapped_candidates(erp)
        real = failing_on(monkeypatch, ITEM, OperationalError("SELECT 1", {}, _PgError("57014")))  # statement_timeout

        with pytest.raises(OperationalError):
            run(True)

        assert (link(erp, OTHER)["source"], link(erp, OTHER)["producto_item_id"]) == ("manual", 42)  # committed
        assert link(erp)["source"] == "sku_auto"

        monkeypatch.setattr(links, "seed_manual_link", real)  # the timeout is gone
        counts = run(True)

        assert (counts.candidates, counts.seeded) == (1, 1)  # OTHER is no longer a candidate
        assert (link(erp)["source"], link(erp)["producto_item_id"]) == ("manual", 41)
        assert len(log_rows(erp)) == 2

    def test_a_stopping_error_reports_the_partial_counts_first(self, erp, monkeypatch, capsys) -> None:
        two_mapped_candidates(erp)
        failing_on(monkeypatch, ITEM, OperationalError("SELECT 1", {}, _PgError("57014")))

        with pytest.raises(OperationalError):
            run(True)

        err = capsys.readouterr().err
        assert "STOPPED" in err
        assert "candidates: 2" in err and "seeded: 1" in err  # OTHER was committed before ITEM failed


class TestUnitsThatChangedMeanwhile:
    """`seed_manual_link` re-reads the unit under its lock; one no longer automatic and unlinked is left alone."""

    def test_a_manual_decision_written_meanwhile_is_left_untouched(self, erp, monkeypatch) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "X")
        add_product(erp, 50, "OPERATOR-PICK")
        erp_map(erp, ITEM, 41, 1)
        real = links.evaluate_for_item

        def operator_decides_first(db, item_id, **kwargs):
            # An operator's manual link commits after the candidate list was read, before this item is seeded.
            with erp.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE ml_item_product_links SET source = 'manual', match_status = 'linked', "
                        "producto_item_id = 50, linked_by = 17 WHERE item_id = :i AND variation_id = 0"
                    ),
                    {"i": item_id},
                )
            return real(db, item_id, **kwargs)

        monkeypatch.setattr(links, "evaluate_for_item", operator_decides_first)

        counts = run(True)

        assert (counts.candidates, counts.changed, counts.seeded) == (1, 1, 0)
        row = link(erp)
        assert (row["source"], row["producto_item_id"], row["linked_by"], row["note"]) == ("manual", 50, 17, None)
        assert log_rows(erp) == []

    def test_an_automatic_unit_in_another_status_is_left_untouched(self, erp, monkeypatch) -> None:
        # The re-evaluation never leaves an automatic unit in `no_product` (the schema allows it): this pins the
        # guard for a row it did not rewrite, so the evaluation is skipped here.
        apply(sample_item(ITEM), ITEM)
        put_link(erp, ITEM, 0, "sku_auto", "no_product", None, evaluated_sku_key=SKU_A, evaluated_at=at(-60))
        add_product(erp, 41, "X")
        monkeypatch.setattr(links, "evaluate_for_item", lambda db, item_id, **kwargs: None)

        with database.get_background_db() as db:
            outcome = links.seed_manual_link(
                db, ITEM, 41, note=seed.SEED_NOTE, match_rule=seed.MATCH_RULE, now=at(10), events_enabled=False
            )

        assert outcome == links.SEED_CHANGED
        row = link(erp)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "no_product", None)
        assert log_rows(erp) == []


class TestErpMapRows:
    def test_two_map_rows_to_the_same_product_seed_it(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "X")
        erp_map(erp, ITEM, 41, 1)
        erp_map(erp, ITEM, 41, 2)

        counts = run(True)

        assert (counts.seeded, counts.ambiguous) == (1, 0)
        assert link(erp)["producto_item_id"] == 41

    def test_two_map_rows_to_different_products_are_ambiguous(self, erp) -> None:
        apply(sample_item(ITEM), ITEM)
        unmatched(erp)
        add_product(erp, 41, "X")
        add_product(erp, 42, "Y")
        erp_map(erp, ITEM, 41, 1)
        erp_map(erp, ITEM, 42, 2)

        counts = run(True)

        assert (counts.seeded, counts.ambiguous) == (0, 1)
        assert link(erp)["source"] == "sku_auto"
