"""
Recursive publication tree assembly (productos-catalog-family-tree PR2).

Assembles the L0 producto -> L1 (familia | catalogo-outside-family |
publicacion) -> L2+ (catalogos within family / vinculadas via
`ml_item_relations`) -> deeper recursion tree for a single `item_id`,
entirely from PERSISTED data (`publicaciones_ml`, `ml_publication_links`,
`ml_item_relations`) — no live ML calls here (lazy-fill, PR2's endpoint
layer, is responsible for topping up stale/missing link rows BEFORE
calling this function; see `ml_publication_link_service.py`).

Grouping (design decision B — item_id stays the L0 CONTAINER, family_id
is the L1 GROUPING key when present):
  - MLAs sharing the same non-null `family_id` -> one `familia` L1 node,
    with each MLA a child (a `catalogo` L2 node if `catalog_listing`,
    otherwise a plain leaf).
  - MLAs with no `family_id` and `catalog_listing=True` -> their OWN L1
    `catalogo` node (catalog outside any family).
  - MLAs with no `family_id` and `catalog_listing=False` -> a plain L1
    `publicacion` leaf.
  - An MLA with NO `ml_publication_links` row at all (lazy-fill never
    ran, or the proxy was down) falls back to a plain leaf too
    (fail-open — matches the flat endpoint's degrade-gracefully
    behavior, never crashes the whole tree).

Recursion (vinculadas): for any MLA-bearing node, `ml_item_relations`
edges (`mla`/`related_mla`, stored BIDIRECTIONALLY by ML — both A->B and
B->A rows exist) are followed to attach `vinculada` children, genuinely
unbounded depth (no hardcoded max), guarded by a per-tree visited-set so
a bidirectional 2-node edge or a longer cycle (e.g. A->B->C->A) cannot
infinite-loop or duplicate nodes.

Audit-driven skip+flag (join-existing assumption is NOT 100%, see
`audit_publication_link_coverage.py`): an edge is only followed if the
related MLA resolves to a `publicaciones_ml` row belonging to the SAME
`item_id`. Otherwise it is SKIPPED from the tree (never attached, never
raises) and recorded in `skipped_edges` so a later report can surface
it:
  - "cross_item": related MLA tracked but under a DIFFERENT item_id.
  - "unresolvable": related MLA has no `publicaciones_ml` row at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.models.publicacion_ml import PublicacionML
from app.schemas.productos_tree import ProductTreeResponse, SkippedEdge, TreeNode


@dataclass
class _LinkRow:
    family_id: Optional[str]
    catalog_listing: bool
    catalog_product_id: Optional[str]


@dataclass
class _AssemblyContext:
    """Mutable state threaded through the recursive assembly."""

    item_id: int
    links_by_mla: Dict[str, _LinkRow]
    edges_by_mla: Dict[str, List[str]]
    item_id_by_mla: Dict[str, Optional[int]]
    matches_filter_by_mla: Dict[str, bool]
    visited: Set[str] = field(default_factory=set)
    skipped_edges: List[SkippedEdge] = field(default_factory=list)


def assemble_publication_tree(
    db: Session,
    item_id: int,
    matches_filter_by_mla: Optional[Dict[str, bool]] = None,
) -> ProductTreeResponse:
    """Assembles the recursive publication tree for `item_id`.

    Args:
        db: Open SQLAlchemy session. Read-only — this function performs
            NO writes (lazy-fill, if needed, is the caller's job before
            invoking this).
        item_id: The ERP product id to assemble the tree for.
        matches_filter_by_mla: optional per-MLA `matches_filter` map,
            computed by the CALLER via the exact same
            `select_promo_resolver` dispatch used by the flat lite
            endpoint (single source of truth), bounded to this
            product's own MLAs. `None` (no active filter) or a missing
            key both mean "absent" (fail-open — never hides a node,
            mirrors the flat endpoint's degrade-gracefully behavior).
            Grouping nodes ("producto"/"familia") NEVER carry
            `matches_filter` — only MLA-bearing nodes do.

    Returns:
        `ProductTreeResponse` with the root `producto` node, plus the
        skip+flag anomaly count/list for edges deliberately excluded
        from the tree (cross-item_id or unresolvable related MLAs).
    """
    mlas = [
        row.mla
        for row in db.query(PublicacionML.mla)
        .filter(PublicacionML.item_id == item_id, PublicacionML.activo == True)  # noqa: E712
        .order_by(PublicacionML.id)
        .all()
    ]

    root = TreeNode(level=0, kind="producto", label=f"Producto {item_id}")

    if not mlas:
        return ProductTreeResponse(item_id=item_id, tree=root, skipped_anomalous_edges=0, skipped_edges=[])

    links_by_mla = _load_links(db, mlas)
    edges_by_mla = _load_edges(db, mlas)
    item_id_by_mla = _load_item_id_by_related_mla(db, edges_by_mla)

    ctx = _AssemblyContext(
        item_id=item_id,
        links_by_mla=links_by_mla,
        edges_by_mla=edges_by_mla,
        item_id_by_mla=item_id_by_mla,
        matches_filter_by_mla=matches_filter_by_mla or {},
    )

    # Grouping pass: bucket MLAs into families / standalone-catalog /
    # plain leaves. Order is DETERMINISTIC (not merely "whatever Postgres
    # happens to return") because every underlying query is explicitly
    # `ORDER BY`'d: MLAs by their `publicaciones_ml.id` (insertion order),
    # links by `mla`, and edges by their `ml_item_relations.id` (insertion
    # order) — without this, an edge/mla read in a different relative
    # order across runs could non-deterministically flip which MLA ends up
    # "primary" vs attached as a `vinculada` under it.
    families: Dict[str, List[str]] = {}
    standalone: List[str] = []

    for mla in mlas:
        link = links_by_mla.get(mla)
        family_id = link.family_id if link else None
        if family_id:
            families.setdefault(family_id, []).append(mla)
        else:
            standalone.append(mla)

    for family_id, family_mlas in families.items():
        familia_node = TreeNode(level=1, kind="familia", family_id=family_id, label=f"Familia {family_id}")
        for mla in family_mlas:
            if mla in ctx.visited:
                # Already attached elsewhere as a vinculada child (e.g. a
                # sibling family's catalog linked back to this mla) —
                # never render the SAME mla twice in one tree.
                continue
            familia_node.children.append(_build_mla_node(mla, level=2, ctx=ctx))
        if familia_node.children:
            # A family whose every member was already consumed elsewhere
            # (attached as a vinculada under a sibling family/catalog via
            # `ctx.visited`) would otherwise render as an empty phantom
            # node — only append families that ended up with content.
            root.children.append(familia_node)

    for mla in standalone:
        if mla in ctx.visited:
            # Already attached as a `vinculada` under some catalog/family
            # node above — a plain/standalone MLA reached via
            # `ml_item_relations` must not ALSO appear as its own root
            # sibling.
            continue
        root.children.append(_build_mla_node(mla, level=1, ctx=ctx))

    return ProductTreeResponse(
        item_id=item_id,
        tree=root,
        skipped_anomalous_edges=len(ctx.skipped_edges),
        skipped_edges=ctx.skipped_edges,
    )


def _build_mla_node(mla: str, level: int, ctx: _AssemblyContext) -> TreeNode:
    """Builds one MLA-bearing node (catalogo/vinculada/publicacion) and
    recurses into its `vinculada` children via `ml_item_relations`,
    guarded by `ctx.visited` against cycles."""
    link = ctx.links_by_mla.get(mla)
    catalog_listing = bool(link.catalog_listing) if link else False
    catalog_product_id = link.catalog_product_id if link else None

    kind = "catalogo" if catalog_listing else "publicacion"
    node = TreeNode(
        level=level,
        kind=kind,
        mla=mla,
        catalog_product_id=catalog_product_id,
        label=mla,
        matches_filter=ctx.matches_filter_by_mla.get(mla),
    )

    ctx.visited.add(mla)
    node.children = _build_vinculadas(mla, level=level + 1, ctx=ctx)
    return node


def _build_vinculadas(mla: str, level: int, ctx: _AssemblyContext) -> List[TreeNode]:
    """Follows `ml_item_relations` edges from `mla`, skipping+flagging
    cross-item_id/unresolvable related MLAs and cycle-guarding via
    `ctx.visited`."""
    children: List[TreeNode] = []

    for related_mla in ctx.edges_by_mla.get(mla, []):
        if related_mla in ctx.visited:
            # Cycle guard: bidirectional edges (A<->B) or longer cycles
            # (A->B->C->A) would otherwise recurse forever / duplicate.
            continue

        related_item_id = ctx.item_id_by_mla.get(related_mla)
        if related_item_id is None:
            ctx.skipped_edges.append(SkippedEdge(mla=mla, related_mla=related_mla, reason="unresolvable"))
            continue
        if related_item_id != ctx.item_id:
            ctx.skipped_edges.append(SkippedEdge(mla=mla, related_mla=related_mla, reason="cross_item"))
            continue

        ctx.visited.add(related_mla)
        link = ctx.links_by_mla.get(related_mla)
        vinculada = TreeNode(
            level=level,
            kind="vinculada",
            mla=related_mla,
            catalog_product_id=link.catalog_product_id if link else None,
            label=related_mla,
            matches_filter=ctx.matches_filter_by_mla.get(related_mla),
        )
        vinculada.children = _build_vinculadas(related_mla, level=level + 1, ctx=ctx)
        children.append(vinculada)

    return children


def _load_links(db: Session, mlas: List[str]) -> Dict[str, _LinkRow]:
    """Loads `ml_publication_links` rows for `mlas` into a lookup dict.
    An mla with NO row is simply absent (fail-open leaf fallback)."""
    rows = db.query(MlPublicationLink).filter(MlPublicationLink.mla.in_(mlas)).order_by(MlPublicationLink.mla).all()
    return {
        row.mla: _LinkRow(
            family_id=row.family_id,
            catalog_listing=bool(row.catalog_listing),
            catalog_product_id=row.catalog_product_id,
        )
        for row in rows
    }


def _load_edges(db: Session, mlas: List[str]) -> Dict[str, List[str]]:
    """Loads `ml_item_relations` edges for `mlas`, keyed by `mla` ->
    ordered list of `related_mla`. Only edges originating FROM this
    product's own MLAs are loaded (bidirectional storage means the
    reverse edge, if relevant, is reached when recursing into the
    related MLA itself)."""
    rows = db.query(MlItemRelation).filter(MlItemRelation.mla.in_(mlas)).order_by(MlItemRelation.id).all()
    edges: Dict[str, List[str]] = {}
    for row in rows:
        edges.setdefault(row.mla, []).append(row.related_mla)
    return edges


def _load_item_id_by_related_mla(db: Session, edges_by_mla: Dict[str, List[str]]) -> Dict[str, Optional[int]]:
    """Resolves every related_mla referenced by `edges_by_mla` to its
    `publicaciones_ml.item_id` (None if unresolvable/untracked)."""
    related_mlas: Set[str] = set()
    for targets in edges_by_mla.values():
        related_mlas.update(targets)

    if not related_mlas:
        return {}

    rows: List[Tuple[str, int]] = (
        db.query(PublicacionML.mla, PublicacionML.item_id).filter(PublicacionML.mla.in_(related_mlas)).all()
    )
    return {mla: iid for mla, iid in rows}
