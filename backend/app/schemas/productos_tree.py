"""
Response schemas for the recursive product publication tree
(productos-catalog-family-tree PR2).

`TreeNode` is genuinely recursive (unbounded depth) — see
`app/services/ml_publication_tree_service.py` for the assembly algorithm
and `AGENTS.md`/design doc `sdd/productos-catalog-family-tree/design`
for the level/kind semantics.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SkippedEdge(BaseModel):
    """One `ml_item_relations` edge that was deliberately NOT attached to
    the tree (skip+flag decision from the coverage audit).

    `reason` is one of:
      - "cross_item": the related MLA is tracked but belongs to a
        DIFFERENT `item_id` (outside this product's join-existing tree).
      - "unresolvable": the related MLA has no `publicaciones_ml` row at
        all (untracked).
    """

    mla: str
    related_mla: str
    reason: str


class TreeNodePromoSummary(BaseModel):
    """Collapsed-node promo summary attached to MLA-bearing nodes
    (catalog-tree-node-summary PR). Restores the per-MLA promo badges the
    old flat panel showed, now visible WITHOUT expanding the node.

    `applied_markup` is intentionally NOT included yet — computing it
    requires the same per-MLA pricing pipeline `fetch_item_promotions` runs
    (product cost/commission), which would turn this batched summary into
    an N+1 call per MLA. See `assemble_publication_tree`'s docstring for the
    deferred-markup rationale; the FE can show it once a node is expanded
    (the per-MLA promos panel already computes it today).
    """

    started_count: int
    candidate_count: int
    applied_name: Optional[str] = None
    applied_price: Optional[float] = None


class TreeNode(BaseModel):
    """One node of the recursive publication tree.

    `kind` is one of "producto" | "familia" | "catalogo" | "vinculada" |
    "publicacion". Grouping nodes ("producto"/"familia") have no `mla`;
    MLA-bearing nodes ("catalogo"/"vinculada"/"publicacion") carry `mla`
    and an optional `matches_filter` (fail-open promo filter, same
    dispatch as the flat lite endpoint).

    `publication_status` restores the per-publication status badge the
    old flat MLA panel showed ("active"/"paused"/"closed"/
    "under_review", or `status_{id}` for an unmapped ERP id) — see
    `ml_publication_status_service.resolve_publication_status`. Like
    `lista_nombre`, it is only ever set on MLA-bearing nodes; grouping
    nodes ("producto"/"familia") always leave it `None`, and so does any
    MLA the ERP mirror does not know about (fail-open: no badge, never a
    fabricated one).

    Promos are INTENTIONALLY NOT assembled server-side here (design
    decision, PR2): the FE fetches them per-MLA via the existing,
    unchanged `MlaPromocionesPanel`/per-MLA promos mechanism at
    whatever depth a leaf node sits (PR3), reusing `fetch_item_promotions`
    exactly as today — this endpoint only returns the tree shape.
    """

    level: int
    kind: str
    mla: Optional[str] = None
    family_id: Optional[str] = None
    catalog_product_id: Optional[str] = None
    label: str
    matches_filter: Optional[bool] = None
    promo_summary: Optional[TreeNodePromoSummary] = None
    lista_nombre: Optional[str] = None
    pricelist_id: Optional[int] = None
    publication_status: Optional[str] = None
    children: List["TreeNode"] = Field(default_factory=list)


TreeNode.model_rebuild()


class ProductTreeResponse(BaseModel):
    """Root response for `GET /productos/{item_id}/mercadolibre/tree`."""

    item_id: int
    tree: TreeNode
    skipped_anomalous_edges: int = 0
    skipped_edges: List[SkippedEdge] = Field(default_factory=list)
