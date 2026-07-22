"""
RED/GREEN — recursive publication tree assembly
(productos-catalog-family-tree PR2, task 11/12).

Covers the grouping algorithm from the design doc
(`sdd/productos-catalog-family-tree/design`):
  L0 producto (item_id) -> L1 familia (if family_id present) OR
  catalogo-outside-family OR plain publicacion -> L2 catalogos within a
  family / vinculadas (via `ml_item_relations`) -> deeper recursion,
  genuinely unbounded (no hardcoded max depth), guarded by a visited-set
  against cycles (edges are bidirectional in ML — A->B and B->A both
  exist as rows).

Spec coverage:
  - "assemble a recursive, unbounded-depth tree" (family + catalogs +
    stock-synced vinculadas down to L5).
  - multiple families under one item_id render as sibling L1 groups.
  - plain publication (no family, no catalog) is a flat L1 leaf.
  - MLA missing a `ml_publication_links` row falls back to a flat leaf
    (fail-open), never crashes.
  - a 2-node cycle (A<->B) and a 3-node cycle (A->B->C->A) both
    terminate via the visited-set guard, without infinite recursion or
    duplicate nodes.
  - cross-item_id / unresolvable edges (audit-driven "skip+flag") are
    skipped from the tree and reported in `skipped_edges` /
    `skipped_anomalous_edges`, never attached and never crash.
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


def _seed_pub(db, mla: str, item_id: int, pricelist_id: int = 4) -> None:
    db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=pricelist_id, activo=True))


def _seed_link(
    db,
    mla: str,
    item_id: int,
    family_id: str | None = None,
    catalog_listing: bool = False,
    catalog_product_id: str | None = None,
) -> None:
    db.add(
        MlPublicationLink(
            mla=mla,
            item_id=item_id,
            family_id=family_id,
            catalog_listing=catalog_listing,
            catalog_product_id=catalog_product_id,
        )
    )


class TestPlainPublication:
    def test_no_family_no_catalog_is_flat_leaf(self, db) -> None:
        _seed_producto(db, 1)
        _seed_pub(db, "MLA1", 1)
        _seed_link(db, "MLA1", 1)
        db.commit()

        result = assemble_publication_tree(db, item_id=1)

        assert result.tree.kind == "producto"
        assert len(result.tree.children) == 1
        leaf = result.tree.children[0]
        assert leaf.kind == "publicacion"
        assert leaf.mla == "MLA1"
        assert leaf.children == []
        assert result.skipped_anomalous_edges == 0


class TestFailOpenFallback:
    def test_mla_missing_link_row_is_flat_leaf(self, db) -> None:
        _seed_producto(db, 2)
        _seed_pub(db, "MLA2", 2)
        # deliberately no MlPublicationLink row for MLA2
        db.commit()

        result = assemble_publication_tree(db, item_id=2)

        assert len(result.tree.children) == 1
        leaf = result.tree.children[0]
        assert leaf.kind == "publicacion"
        assert leaf.mla == "MLA2"


class TestFamilyGrouping:
    def test_family_with_catalogs_and_vinculadas(self, db) -> None:
        _seed_producto(db, 3)
        _seed_pub(db, "MLA_FAM_CAT", 3)
        _seed_pub(db, "MLA_FAM_VINC", 3)
        _seed_link(db, "MLA_FAM_CAT", 3, family_id="FAM1", catalog_listing=True, catalog_product_id="CP1")
        _seed_link(db, "MLA_FAM_VINC", 3, family_id=None, catalog_listing=False)
        db.add(MlItemRelation(mla="MLA_FAM_CAT", related_mla="MLA_FAM_VINC", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=3)

        assert len(result.tree.children) == 1
        familia = result.tree.children[0]
        assert familia.kind == "familia"
        assert familia.family_id == "FAM1"
        assert len(familia.children) == 1
        catalogo = familia.children[0]
        assert catalogo.kind == "catalogo"
        assert catalogo.mla == "MLA_FAM_CAT"
        assert len(catalogo.children) == 1
        vinculada = catalogo.children[0]
        assert vinculada.kind == "vinculada"
        assert vinculada.mla == "MLA_FAM_VINC"

    def test_multiple_families_render_as_siblings(self, db) -> None:
        _seed_producto(db, 4)
        _seed_pub(db, "MLA_A", 4)
        _seed_pub(db, "MLA_B", 4)
        _seed_link(db, "MLA_A", 4, family_id="FAM_A")
        _seed_link(db, "MLA_B", 4, family_id="FAM_B")
        db.commit()

        result = assemble_publication_tree(db, item_id=4)

        family_ids = {child.family_id for child in result.tree.children if child.kind == "familia"}
        assert family_ids == {"FAM_A", "FAM_B"}


class TestCatalogOutsideFamily:
    def test_catalog_without_family_is_own_l1_node(self, db) -> None:
        _seed_producto(db, 5)
        _seed_pub(db, "MLA_CAT_ALONE", 5)
        _seed_link(db, "MLA_CAT_ALONE", 5, family_id=None, catalog_listing=True, catalog_product_id="CPX")
        db.commit()

        result = assemble_publication_tree(db, item_id=5)

        assert len(result.tree.children) == 1
        node = result.tree.children[0]
        assert node.kind == "catalogo"
        assert node.mla == "MLA_CAT_ALONE"
        assert node.family_id is None


class TestDeepRecursion:
    def test_unbounded_recursion_to_l5(self, db) -> None:
        # family -> catalog(L2) -> vinc1(L3) -> vinc2(L4) -> vinc3(L5)
        _seed_producto(db, 6)
        for mla in ["MLA_CAT", "MLA_V1", "MLA_V2", "MLA_V3"]:
            _seed_pub(db, mla, 6)
        _seed_link(db, "MLA_CAT", 6, family_id="FAM_DEEP", catalog_listing=True, catalog_product_id="CPD")
        _seed_link(db, "MLA_V1", 6)
        _seed_link(db, "MLA_V2", 6)
        _seed_link(db, "MLA_V3", 6)
        db.add(MlItemRelation(mla="MLA_CAT", related_mla="MLA_V1", stock_relation=1))
        db.add(MlItemRelation(mla="MLA_V1", related_mla="MLA_V2", stock_relation=1))
        db.add(MlItemRelation(mla="MLA_V2", related_mla="MLA_V3", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=6)

        familia = result.tree.children[0]
        catalogo = familia.children[0]
        assert catalogo.level == 2
        v1 = catalogo.children[0]
        assert v1.level == 3
        assert v1.mla == "MLA_V1"
        v2 = v1.children[0]
        assert v2.level == 4
        assert v2.mla == "MLA_V2"
        v3 = v2.children[0]
        assert v3.level == 5
        assert v3.mla == "MLA_V3"
        assert v3.children == []


class TestCycleGuard:
    def test_two_node_cycle_terminates(self, db) -> None:
        _seed_producto(db, 7)
        _seed_pub(db, "MLA_X", 7)
        _seed_pub(db, "MLA_Y", 7)
        _seed_link(db, "MLA_X", 7, catalog_listing=True, catalog_product_id="CX")
        _seed_link(db, "MLA_Y", 7)
        # ML relations are bidirectional: both directions are stored.
        db.add(MlItemRelation(mla="MLA_X", related_mla="MLA_Y", stock_relation=1))
        db.add(MlItemRelation(mla="MLA_Y", related_mla="MLA_X", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=7)

        catalogo = result.tree.children[0]
        assert catalogo.mla == "MLA_X"
        assert len(catalogo.children) == 1
        vinc = catalogo.children[0]
        assert vinc.mla == "MLA_Y"
        # Y must NOT loop back to X as a child (visited-set guard).
        assert vinc.children == []

    def test_three_node_cycle_terminates(self, db) -> None:
        _seed_producto(db, 8)
        _seed_pub(db, "MLA_A", 8)
        _seed_pub(db, "MLA_B", 8)
        _seed_pub(db, "MLA_C", 8)
        _seed_link(db, "MLA_A", 8, catalog_listing=True, catalog_product_id="CA")
        _seed_link(db, "MLA_B", 8)
        _seed_link(db, "MLA_C", 8)
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_B", stock_relation=1))
        db.add(MlItemRelation(mla="MLA_B", related_mla="MLA_C", stock_relation=1))
        db.add(MlItemRelation(mla="MLA_C", related_mla="MLA_A", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=8)

        catalogo = result.tree.children[0]
        assert catalogo.mla == "MLA_A"
        b = catalogo.children[0]
        assert b.mla == "MLA_B"
        c = b.children[0]
        assert c.mla == "MLA_C"
        # C must NOT loop back to A.
        assert c.children == []


class TestSkipAndFlagAnomalousEdges:
    def test_cross_item_edge_is_skipped_and_flagged(self, db) -> None:
        _seed_producto(db, 9)
        _seed_producto(db, 900)
        _seed_pub(db, "MLA_SELF", 9)
        _seed_pub(db, "MLA_OTHER_ITEM", 900)
        _seed_link(db, "MLA_SELF", 9, catalog_listing=True, catalog_product_id="CS")
        db.add(MlItemRelation(mla="MLA_SELF", related_mla="MLA_OTHER_ITEM", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=9)

        catalogo = result.tree.children[0]
        assert catalogo.children == []
        assert result.skipped_anomalous_edges == 1
        assert result.skipped_edges[0].reason == "cross_item"
        assert result.skipped_edges[0].related_mla == "MLA_OTHER_ITEM"

    def test_unresolvable_edge_is_skipped_and_flagged(self, db) -> None:
        _seed_producto(db, 10)
        _seed_pub(db, "MLA_SELF2", 10)
        _seed_link(db, "MLA_SELF2", 10, catalog_listing=True, catalog_product_id="CS2")
        db.add(MlItemRelation(mla="MLA_SELF2", related_mla="MLA_UNKNOWN", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=10)

        catalogo = result.tree.children[0]
        assert catalogo.children == []
        assert result.skipped_anomalous_edges == 1
        assert result.skipped_edges[0].reason == "unresolvable"
        assert result.skipped_edges[0].related_mla == "MLA_UNKNOWN"

    def test_zero_mlas_returns_empty_producto_root(self, db) -> None:
        _seed_producto(db, 11)
        db.commit()

        result = assemble_publication_tree(db, item_id=11)

        assert result.tree.kind == "producto"
        assert result.tree.children == []
        assert result.skipped_anomalous_edges == 0


class TestNoEmptyPhantomFamilyNode:
    def test_family_fully_consumed_elsewhere_does_not_render_empty(self, db) -> None:
        """Family A's own MLA links out to family B's ONLY member. Since
        the vinculada visit marks that mla `visited`, family B's grouping
        pass has nothing left to attach — it must NOT still append an
        empty 'familia' node with zero children (review fix 2/4)."""
        _seed_producto(db, 12)
        _seed_pub(db, "MLA_FAM_A", 12)
        _seed_pub(db, "MLA_FAM_B", 12)
        _seed_link(db, "MLA_FAM_A", 12, family_id="FAM_A", catalog_listing=True, catalog_product_id="CA")
        _seed_link(db, "MLA_FAM_B", 12, family_id="FAM_B")
        db.add(MlItemRelation(mla="MLA_FAM_A", related_mla="MLA_FAM_B", stock_relation=1))
        db.commit()

        result = assemble_publication_tree(db, item_id=12)

        familia_nodes = [child for child in result.tree.children if child.kind == "familia"]
        # FAM_A survives (its own mla is unconsumed); FAM_B must NOT render
        # as an empty phantom node — its only member was already attached
        # as FAM_A's vinculada.
        assert len(familia_nodes) == 1
        assert familia_nodes[0].family_id == "FAM_A"
        assert all(len(node.children) > 0 for node in familia_nodes)

    def test_legitimately_populated_family_still_renders(self, db) -> None:
        _seed_producto(db, 13)
        _seed_pub(db, "MLA_POP", 13)
        _seed_link(db, "MLA_POP", 13, family_id="FAM_POP")
        db.commit()

        result = assemble_publication_tree(db, item_id=13)

        familia_nodes = [child for child in result.tree.children if child.kind == "familia"]
        assert len(familia_nodes) == 1
        assert familia_nodes[0].family_id == "FAM_POP"
        assert len(familia_nodes[0].children) == 1


class TestDeterministicOrdering:
    def test_assembling_twice_yields_identical_child_order(self, db) -> None:
        _seed_producto(db, 14)
        # Seeded in a specific insertion order — deterministic ordering is
        # by `publicaciones_ml.id` (insertion order), NOT alphabetical, so
        # this order is preserved across repeated assembly.
        _seed_pub(db, "MLA_Z", 14, pricelist_id=23)
        _seed_pub(db, "MLA_A", 14, pricelist_id=4)
        _seed_pub(db, "MLA_M", 14, pricelist_id=14)
        _seed_link(db, "MLA_Z", 14)
        _seed_link(db, "MLA_A", 14)
        _seed_link(db, "MLA_M", 14)
        db.commit()

        first = assemble_publication_tree(db, item_id=14)
        second = assemble_publication_tree(db, item_id=14)

        first_order = [child.mla for child in first.tree.children]
        second_order = [child.mla for child in second.tree.children]
        assert first_order == second_order
        # Documented deterministic order: publicaciones_ml.id (insertion
        # order), matching seed order here.
        assert first_order == ["MLA_Z", "MLA_A", "MLA_M"]


class TestPromoNodeSummaryAttachment:
    """catalog-tree-node-summary PR — `assemble_publication_tree` batch-
    attaches an optional `promo_summary` (caller-supplied, one batched
    fetch, no N+1) to every MLA-bearing node."""

    def test_mla_bearing_node_gets_promo_summary_when_provided(self, db) -> None:
        _seed_producto(db, 20)
        _seed_pub(db, "MLA20", 20)
        _seed_link(db, "MLA20", 20)
        db.commit()

        promo_summary_by_mla = {
            "MLA20": {
                "started_count": 1,
                "candidate_count": 2,
                "applied_name": "Oferta Relámpago",
                "applied_price": 850.0,
            }
        }

        result = assemble_publication_tree(db, item_id=20, promo_summary_by_mla=promo_summary_by_mla)

        leaf = result.tree.children[0]
        assert leaf.mla == "MLA20"
        assert leaf.promo_summary is not None
        assert leaf.promo_summary.started_count == 1
        assert leaf.promo_summary.candidate_count == 2
        assert leaf.promo_summary.applied_name == "Oferta Relámpago"
        assert leaf.promo_summary.applied_price == 850.0

    def test_mla_bearing_node_promo_summary_absent_when_not_provided(self, db) -> None:
        """Fail-open: no summary map at all -> field stays None, never
        crashes, never fabricates a summary."""
        _seed_producto(db, 21)
        _seed_pub(db, "MLA21", 21)
        _seed_link(db, "MLA21", 21)
        db.commit()

        result = assemble_publication_tree(db, item_id=21)

        leaf = result.tree.children[0]
        assert leaf.promo_summary is None

    def test_mla_missing_from_summary_map_stays_none(self, db) -> None:
        """An mla with zero promos never appears as a key in the batched
        map (documented absence) — must not raise, must stay None."""
        _seed_producto(db, 22)
        _seed_pub(db, "MLA22", 22)
        _seed_link(db, "MLA22", 22)
        db.commit()

        result = assemble_publication_tree(db, item_id=22, promo_summary_by_mla={})

        leaf = result.tree.children[0]
        assert leaf.promo_summary is None

    def test_grouping_nodes_never_carry_promo_summary(self, db) -> None:
        _seed_producto(db, 23)
        _seed_pub(db, "MLA23", 23)
        _seed_link(db, "MLA23", 23, family_id="FAM23")
        db.commit()

        promo_summary_by_mla = {
            "MLA23": {"started_count": 0, "candidate_count": 1, "applied_name": None, "applied_price": None}
        }

        result = assemble_publication_tree(db, item_id=23, promo_summary_by_mla=promo_summary_by_mla)

        familia_node = result.tree.children[0]
        assert familia_node.kind == "familia"
        assert familia_node.promo_summary is None
        mla_node = familia_node.children[0]
        assert mla_node.promo_summary is not None

    def test_vinculada_node_also_gets_promo_summary(self, db) -> None:
        _seed_producto(db, 24)
        _seed_pub(db, "MLA_BASE", 24)
        _seed_pub(db, "MLA_VINC", 24)
        _seed_link(db, "MLA_BASE", 24)
        _seed_link(db, "MLA_VINC", 24)
        db.add(MlItemRelation(mla="MLA_BASE", related_mla="MLA_VINC", stock_relation=1))
        db.commit()

        promo_summary_by_mla = {
            "MLA_VINC": {"started_count": 1, "candidate_count": 0, "applied_name": "SMART", "applied_price": 100.0}
        }

        result = assemble_publication_tree(db, item_id=24, promo_summary_by_mla=promo_summary_by_mla)

        base_node = result.tree.children[0]
        vinc_node = base_node.children[0]
        assert vinc_node.mla == "MLA_VINC"
        assert vinc_node.promo_summary is not None
        assert vinc_node.promo_summary.applied_name == "SMART"
