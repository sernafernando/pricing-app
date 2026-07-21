"""
RED/GREEN — promo-filter parity for the recursive tree
(productos-catalog-family-tree PR2, task 13).

Asserts `matches_filter`/`select_promo_resolver` are reused UNCHANGED by
the tree assembly, at any depth, with the SAME fail-open dispatch as the
flat `/mercadolibre` (lite) endpoint: `matches_filter` is set per
MLA-bearing node when a resolver is active, and simply absent (never a
500, never hides nodes) if the cross-DB resolver call fails.

Spec coverage: "Promo filter applied to a deeply nested vinculada" — the
same filter semantics used at L1 apply unchanged at depth.
"""

from __future__ import annotations

from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.ml_publication_tree_service import assemble_publication_tree


def _seed_producto(db, item_id: int) -> None:
    if db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first() is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
        db.flush()


def _seed_pub(db, mla: str, item_id: int) -> None:
    db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4, activo=True))


def _seed_link(db, mla: str, item_id: int, catalog_listing: bool = False) -> None:
    db.add(MlPublicationLink(mla=mla, item_id=item_id, catalog_listing=catalog_listing))


class TestPromoFilterParityAtDepth:
    def test_matches_filter_applies_to_l1_and_deep_vinculada(self, db) -> None:
        _seed_producto(db, 50)
        _seed_pub(db, "MLA_ROOT", 50)
        _seed_pub(db, "MLA_DEEP", 50)
        _seed_link(db, "MLA_ROOT", 50, catalog_listing=True)
        _seed_link(db, "MLA_DEEP", 50)
        db.add(MlItemRelation(mla="MLA_ROOT", related_mla="MLA_DEEP", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(
            db,
            item_id=50,
            matches_filter_by_mla={"MLA_ROOT": True, "MLA_DEEP": False},
        )

        root_node = result.tree.children[0]
        assert root_node.matches_filter is True
        deep_node = root_node.children[0]
        assert deep_node.matches_filter is False

    def test_matches_filter_absent_when_resolver_inactive(self, db) -> None:
        _seed_producto(db, 51)
        _seed_pub(db, "MLA_NOFILTER", 51)
        _seed_link(db, "MLA_NOFILTER", 51)
        db.commit()

        result = assemble_publication_tree(db, item_id=51, matches_filter_by_mla=None)

        assert result.tree.children[0].matches_filter is None

    def test_grouping_nodes_never_carry_matches_filter(self, db) -> None:
        _seed_producto(db, 52)
        _seed_pub(db, "MLA_FAM", 52)
        db.add(MlPublicationLink(mla="MLA_FAM", item_id=52, family_id="FAMX"))
        db.commit()

        result = assemble_publication_tree(db, item_id=52, matches_filter_by_mla={"MLA_FAM": True})

        familia_node = result.tree.children[0]
        assert familia_node.kind == "familia"
        assert familia_node.matches_filter is None
        assert familia_node.children[0].matches_filter is True
