"""One-time seed of manual product links from the ERP publication map, against a real Postgres.

Items are real captures stored through `apply_fetch` (links off); link rows, `productos_erp` and the ERP
map `tb_mercadolibre_items_publicados` (`mlp_publicationid` -> `item_id`) are plain test data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.scripts import seed_vinculos_ml_desde_erp as seed
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
