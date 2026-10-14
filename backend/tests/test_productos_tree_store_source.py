"""
Tree link data comes from the ML publications store, never from the proxy
(perf/productos-promos-first-load, backend tree PR).

Production evidence: the first open of a product's promotions took 25-30 s
because `lazy_fill_links` made one sequential ml-webhook `get_item_full`
render per stale MLA (50 of 50 stale for item 4293) BEFORE the tree was
assembled. The tree request now converges `ml_publication_links` /
`ml_item_relations` from the local store (`ml_items`), with zero HTTP.

Fixtures are CAPTURED ML bodies (`tests/fixtures/ml_publications/
items_bulk_samples_20261006.json`): a two-MLA family whose members are
stock-linked to each other (item_relations both ways), a one-MLA family
with no relations and a no-family item.

Layout:
  * characterization — the tree built from `ml_publication_links` rows
    (the pre-change read path, unchanged) is pinned and must keep passing.
  * store parity — the SAME tree must come out of `ml_items` rows alone.
  * RED structural — the request makes zero ml-webhook calls.
  * closed / gone items — still rendered, never fetched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.endpoints.productos_detail import obtener_arbol_ml_producto
from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.models.ml_publications import MlItem
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services import ml_publication_link_service as link_service
from app.services.ml_publication_tree_service import assemble_publication_tree
from app.services.ml_publications.mappers import map_item
from app.services.ml_webhook_client import ml_webhook_client

FIXTURE = Path(__file__).parent / "fixtures" / "ml_publications" / "items_bulk_samples_20261006.json"
ITEM_ID = 777
FAMILY_A = "5385385211222674"
FAMILY_B = "5457370687625708"
# Captured ids: A1/A2 share FAMILY_A and are stock-linked to each other, B1 is alone in FAMILY_B,
# NOFAM has no family. UNKNOWN is a publication of the product the store has never seen.
A1, A2, B1, NOFAM, UNKNOWN = "MLA874027718", "MLA882393030", "MLA862580589", "MLA1207279308", "MLA999000999"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _bodies() -> dict:
    elements = json.loads(FIXTURE.read_text())["elements"]
    return {e["id"]: e["body"] for e in elements if e["status_code"] == 200}


def _shape(node) -> tuple:
    return (
        node.level,
        node.kind,
        node.mla,
        node.family_id,
        node.catalog_product_id,
        [_shape(child) for child in node.children],
    )


# The tree the old read path produced for this product (pinned from `ml_publication_links` rows).
EXPECTED_TREE = (
    0,
    "producto",
    None,
    None,
    None,
    [
        (
            1,
            "familia",
            None,
            FAMILY_A,
            None,
            [(2, "publicacion", A1, None, "MLA15810042", [(3, "vinculada", A2, None, "MLA15810042", [])])],
        ),
        (1, "familia", None, FAMILY_B, None, [(2, "publicacion", B1, None, "MLA21451930", [])]),
        (1, "publicacion", NOFAM, None, "MLA21488342", []),
        (1, "publicacion", UNKNOWN, None, None, []),
    ],
)


@pytest.fixture
def product(db):
    db.add(ProductoERP(item_id=ITEM_ID, codigo="C777", descripcion="Producto 777"))
    db.flush()
    for mla in (A1, A2, B1, NOFAM, UNKNOWN):
        db.add(PublicacionML(mla=mla, item_id=ITEM_ID, pricelist_id=4, activo=True))
    db.commit()


def _seed_links_the_old_way(db) -> None:
    """What `lazy_fill_links` used to persist from the proxy render."""
    for mla, body in _bodies().items():
        link_service.upsert_link(db, mla, body, ITEM_ID, NOW)
        link_service.replace_relations(db, mla, body.get("item_relations") or [])
    db.commit()


def _seed_store(db, only=None, **overrides) -> None:
    """What the publications worker persists: typed columns + the raw body."""
    for mla, body in _bodies().items():
        if only is not None and mla not in only:
            continue
        db.add(MlItem(**{**map_item(body), **overrides.get(mla, {})}, raw=body, never_existed=False, fetched_at=NOW))
    db.commit()


def _call_endpoint(db):
    with (
        patch("app.api.endpoints.productos_detail.fetch_promo_node_summary_by_mla", return_value={}),
        patch.object(ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={})) as batch,
        patch.object(ml_webhook_client, "get_item_full", new=AsyncMock(return_value=None)) as single,
    ):
        result = obtener_arbol_ml_producto(item_id=ITEM_ID, db=db, current_user=SimpleNamespace(id=1))
    return result, batch, single


class TestCharacterization:
    def test_tree_from_link_rows_is_pinned(self, db, product) -> None:
        _seed_links_the_old_way(db)

        result = assemble_publication_tree(db, item_id=ITEM_ID)

        assert _shape(result.tree) == EXPECTED_TREE
        assert result.skipped_anomalous_edges == 0


class TestStoreParity:
    def test_store_alone_yields_the_same_tree(self, db, product) -> None:
        _seed_store(db)

        result, _, _ = _call_endpoint(db)

        assert _shape(result.tree) == EXPECTED_TREE
        assert result.skipped_anomalous_edges == 0

    def test_store_and_link_rows_agree_field_by_field(self, db, product) -> None:
        """The converged `ml_publication_links` rows equal what the proxy writer persisted."""
        _seed_store(db)
        _call_endpoint(db)
        converged = {r.mla: r for r in db.query(MlPublicationLink).all()}
        edges = sorted((e.mla, e.related_mla, e.stock_relation, e.variation_id) for e in db.query(MlItemRelation))

        db.query(MlPublicationLink).delete()
        db.query(MlItemRelation).delete()
        db.commit()
        _seed_links_the_old_way(db)
        legacy = {r.mla: r for r in db.query(MlPublicationLink).all()}

        assert set(converged) == set(legacy)
        for mla, row in legacy.items():
            for column in ("family_id", "user_product_id", "inventory_id", "catalog_listing", "catalog_product_id"):
                assert getattr(converged[mla], column) == getattr(row, column), (mla, column)
            assert converged[mla].item_id == ITEM_ID
        assert edges == sorted(
            (e.mla, e.related_mla, e.stock_relation, e.variation_id) for e in db.query(MlItemRelation)
        )


class TestNoProxyCalls:
    def test_tree_request_makes_zero_ml_webhook_calls(self, db, product) -> None:
        """Even with NOTHING in the store or the link table (the worst case that used to fetch 50 renders)."""
        result, batch, single = _call_endpoint(db)

        batch.assert_not_called()
        single.assert_not_called()
        assert len(result.tree.children) == 5

    def test_unknown_mla_renders_with_what_is_known(self, db, product) -> None:
        _seed_store(db)

        result, batch, _ = _call_endpoint(db)

        batch.assert_not_called()
        leaf = result.tree.children[-1]
        assert (leaf.kind, leaf.mla, leaf.catalog_product_id) == ("publicacion", UNKNOWN, None)


class TestFallbackToLinkRows:
    def test_mla_missing_from_the_store_keeps_its_link_row(self, db, product) -> None:
        _seed_links_the_old_way(db)
        _seed_store(db, only={A1, A2})  # B1 / NOFAM only exist as link rows

        result, _, _ = _call_endpoint(db)

        assert _shape(result.tree) == EXPECTED_TREE

    def test_store_wins_over_a_stale_link_row(self, db, product) -> None:
        db.add(MlPublicationLink(mla=B1, item_id=ITEM_ID, family_id="OLDFAM", catalog_listing=False))
        db.commit()
        _seed_store(db)

        result, _, _ = _call_endpoint(db)

        assert [c.family_id for c in result.tree.children if c.kind == "familia"] == [FAMILY_A, FAMILY_B]

    def test_row_without_a_body_is_not_data(self, db, product) -> None:
        """`never_existed` rows carry no raw body: the link row (if any) stays authoritative."""
        db.add(MlPublicationLink(mla=B1, item_id=ITEM_ID, family_id="LINKFAM", catalog_listing=False))
        db.add(MlItem(item_id=B1, raw=None, never_existed=True))
        db.commit()

        result, batch, _ = _call_endpoint(db)

        batch.assert_not_called()
        assert "LINKFAM" in [c.family_id for c in result.tree.children]


class TestClosedAndGoneItems:
    def test_closed_and_gone_items_are_still_rendered_and_never_fetched(self, db, product) -> None:
        _seed_store(db, **{B1: {"status": "closed"}, A1: {"gone_at": NOW}})

        result, batch, single = _call_endpoint(db)

        batch.assert_not_called()
        single.assert_not_called()
        assert _shape(result.tree) == EXPECTED_TREE


class TestConvergenceIsIdempotent:
    def test_second_open_writes_nothing(self, db, product) -> None:
        _seed_store(db)
        assert link_service.sync_links_from_store(db, [A1, A2, B1, NOFAM, UNKNOWN], ITEM_ID) > 0

        assert link_service.sync_links_from_store(db, [A1, A2, B1, NOFAM, UNKNOWN], ITEM_ID) == 0

    def test_relation_removed_in_the_store_is_removed_from_edges(self, db, product) -> None:
        _seed_store(db)
        link_service.sync_links_from_store(db, [A1, A2], ITEM_ID)
        row = db.query(MlItem).filter(MlItem.item_id == A1).one()
        row.raw = {**row.raw, "item_relations": []}
        db.commit()

        link_service.sync_links_from_store(db, [A1, A2], ITEM_ID)

        assert db.query(MlItemRelation).filter(MlItemRelation.mla == A1).count() == 0
        assert db.query(MlItemRelation).filter(MlItemRelation.mla == A2).count() == 1

    def test_failure_degrades_without_raising(self, db, product) -> None:
        broken = MagicMock()
        broken.query.side_effect = RuntimeError("boom")

        assert link_service.sync_links_from_store(broken, [A1], ITEM_ID) == 0
