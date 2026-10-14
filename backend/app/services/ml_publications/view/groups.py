"""The nodes of the Agrupado tree of the Publicaciones screen (`GET /ml-publications/view/groups`), counts only.

The tree is grouped by a DIMENSION of the Métricas ML board (owner: "Publicaciones must work like Métricas ML"; here
`marca`, `categoria` and `subcategoria`): the group levels of `HIERARCHIES[dimension]`, then
`producto > [familia] > MLA`. The store stays a FILTER of the request. The default, `marca`,
is the original tree (owner decision 1): `marca > categoria > subcategoria > producto > [familia] > MLA`. A node is
identified by the keys of its ancestors (the request's `path`) plus its own, and the page lists the children of the
node the path names, lazily, one level per request.

Reused from the Métricas ML board (`app/services/ml_daily_metrics/groups.py`), not rewritten: `HIERARCHIES` fixes
the group levels above the products, `dimension_of` builds each level's key and label (trimmed and upper-cased text,
the subcategory id and its name, the subcategory in its category), `title_of` the display name and its "Sin ..."
fallbacks, and `NO_GROUP` (`__none__`) is the key of "no brand / category / subcategory / product". Two levels are
new: the product (the linked product of the publication) and the family.

Rules worth knowing before reading the code:

* Every publication is in exactly ONE node of every level, so the counts of a level add up to their parent's.
  A publication with no linked product has no brand, category or subcategory either: it sits under the `__none__`
  brand, category and subcategory, in a "Sin producto" product node (`__none__`) whose children are the MLAs.
* A node's `count` is the `/items` total with the node's own filters (`params`): the node is built from the SAME
  base select (`filters.build_base_select`) the list is, so the two cannot disagree. `params` is what the screen
  appends to the user's filters to fetch the publications of a node; the leaves are never served by this module.
* Families are optional (`familias`, off by default). With them on, a product that has a family of two or more
  publications stops being a leaf; opening it lists those families as nodes, and the publications that share their
  family with no other publication of the product stay as `item` nodes (an MLA is not a family of one).
* The statement count is fixed whatever the number of nodes: one page query, which carries the count of the level in
  a window column; a second, count-only statement runs only when the page is empty (an offset past the end).
* With a `MarkupQuery` (the caller may see margins) each node also carries `negative_count`, `markup_min` and
  `markup_max` (owner decision 7: no average, no Ads sum). They are aggregated in Python from P6's
  computation (`compute_markups`: one inputs pass and one shipping batch, Ads applied when asked) over the
  publications of the page's nodes, which one query names (the node of each publication), so the statements stay fixed and `negative_count` equals the `/items`
  total with `markup_neg` under the node's `params`.

Postgres only (`bool_or`); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics.groups import (
    HIERARCHIES,
    NO_GROUP,
    SUBCATEGORIA_IN_CATEGORIA,
    SUBCATEGORIA_KEY_SEPARATOR,
    Dimension,
    dimension_of,
    title_of,
)
from app.services.ml_publications.view.filters import (
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    decode_key,
    encode_key,
)
from app.services.ml_publications.view.listing import resolve_pm_pairs
from app.services.ml_publications.view.markup_service import MarkupQuery, aggregate_nodes, compute_markups, gc_paused

KIND_PRODUCT = "producto"
KIND_FAMILY = "familia"
KIND_ITEM = "item"
DEFAULT_DIMENSION = "marca"
# The dimensions of the Métricas board this tree is grouped by; the group levels of each are the board's own
# hierarchy (`HIERARCHIES`) and the tree adds the products (and the families) below them.
DIMENSIONS = ("marca", "categoria", "subcategoria")
DEFAULT_LIMIT = 100
MAX_LIMIT = 100
NO_PRODUCT_LABEL = "Sin producto"
FAMILY_MIN_SIZE = 2  # a family of one publication is that publication, not a node
ITEM_IDS_MAX = 5_000  # most publications priced by an id list; above it the whole filter is priced instead

# /items parameter of each level (`params` of a node); the leaves are fetched with them
PARAM_OF = {"marca": "marcas", "categoria": "categorias", "subcategoria": "subcategorias"}
# the keys of these levels are ids, `NO_GROUP` for none
ID_LEVELS = ("subcategoria", KIND_PRODUCT)
PARAM_NO_PRODUCT = "sin_producto"
PARAM_PRODUCT = "producto"
PARAM_FAMILY = "familia"
PARAM_ITEM = "q"  # an MLA id is an exact key of the search


@dataclass(frozen=True)
class Node:
    kind: str
    key: str
    label: str
    count: int
    leaf: bool  # its children are publications: fetch them from `/items` with `params`
    params: dict[str, str]  # the `/items` filters of this node, ancestors included
    producto_item_id: Optional[int] = None
    codigo: Optional[str] = None
    family_id: Optional[int] = None
    item_id: Optional[str] = None
    # markup figures: only with a `MarkupQuery` (`ml_metricas.ver_ganancia`); `markup_min/max` None = no value
    negative_count: Optional[int] = None
    markup_min: Optional[float] = None
    markup_max: Optional[float] = None


@dataclass(frozen=True)
class GroupsPage:
    level: str
    nodes: list[Node]
    total: int  # nodes of the level (not publications), for paging
    ads_failed: bool = False  # the Ads provider raised: the figures are the plain markup


def levels_of(dimension: str) -> tuple[str, ...]:
    """The levels of the tree grouped by `dimension`, top first: Métricas' group levels, then the products (the
    families, when on, are below them). `FilterError` for a dimension this tree is not grouped by."""
    if dimension not in DIMENSIONS:
        raise FilterError("dimension", f"unknown value {dimension!r}; known: {', '.join(DIMENSIONS)}")
    return (*HIERARCHIES[dimension], KIND_PRODUCT)


@dataclass(frozen=True)
class Tree:
    """The tree of one request: its levels and the key/label/joins of each group level, built ONCE per request
    (the columns and the joins of the dimensions must be the same aliases)."""

    levels: tuple[str, ...]
    dimensions: dict[str, Dimension]

    @property
    def group_levels(self) -> tuple[str, ...]:
        return self.levels[:-1]


def tree_of(dimension: str) -> Tree:
    levels = levels_of(dimension)
    dimensions = {
        name: dimension_of(
            name,
            marca=T.p.marca,
            categoria=T.p.categoria,
            subcategoria_id=T.p.subcategoria_id,
            store_id=T.i.official_store_id,
        )
        for name in levels[:-1]
    }
    return Tree(levels, dimensions)


def _nodes_in_level() -> Any:
    """The number of nodes of the level, as a column of its page query: a window over the grouped rows is computed
    before `LIMIT`/`OFFSET` cut the page, so every row of the page carries it and no second pass over the base select
    is needed to count."""
    return func.count().over().label("nodes_in_level")


def _total(db: Session, page: list[Any], key: Any) -> int:
    """Nodes of the level: read off the page's rows, or counted on its own when the page is empty (an offset past
    the end carries no row to read it from)."""
    if page:
        return page[0][-1]
    return db.execute(select(func.count(func.distinct(key)))).scalar_one()


def product_key() -> Any:
    return case((T.p.item_id.is_(None), literal(NO_GROUP)), else_=cast(T.p.item_id, String))


def family_key() -> Any:
    """`COALESCE(family_id, item_id)`: a publication with no family is its own group of one."""
    return func.coalesce(cast(T.i.family_id, String), T.i.item_id)


def level_of(tree: Tree, path: list[str], familias: bool) -> str:
    """The level whose nodes `path` lists; `FilterError` when `path` names a node that has no child nodes."""
    family_depth = len(tree.levels)  # the depth at which the children of a product are listed (families on)
    deepest = family_depth if familias else family_depth - 1
    if len(path) > deepest:
        raise FilterError("path", "that node has no child nodes: its publications come from /items")
    return (*tree.levels, KIND_FAMILY)[len(path)]


# the levels whose keys hold free text (a brand, a category), and so travel percent-escaped
TEXT_LEVELS = ("marca", "categoria", SUBCATEGORIA_IN_CATEGORIA)


def _wire_key(level: str, key: str) -> str:
    """The key of a node as the client sees it: a brand or category with a comma is escaped, so it stays ONE CSV value."""
    return encode_key(key) if level in TEXT_LEVELS else key


def _raw_key(level: str, key: str) -> str:
    return decode_key(key) if level in TEXT_LEVELS else key


def _is_id(key: str) -> bool:
    return key == NO_GROUP or (key.isascii() and key.isdigit())


def _valid_key(level: str, key: str) -> bool:
    """Whether `key` can be a key of `level`: ids (`__none__` for none) where the level is keyed by an id, the id and
    the category of a subcategory in its category; any text for a brand or a category."""
    if level in ID_LEVELS:
        return _is_id(key)
    if level == SUBCATEGORIA_IN_CATEGORIA:
        subcategoria, separator, categoria = key.partition(SUBCATEGORIA_KEY_SEPARATOR)
        return bool(separator) and _is_id(subcategoria) and bool(categoria)
    return True


def _check_path(tree: Tree, path: list[str]) -> None:
    """Each key of the path is checked by the KIND of the level it sits at, whatever its depth."""
    for depth, key in enumerate(path[: len(tree.levels)]):
        if not _valid_key(tree.levels[depth], key):
            raise FilterError("path", f"{key!r} is not a {tree.levels[depth]} key")


def _scoped(f: PublicationFilter, path: list[str], tree: Tree, *columns: Any) -> Any:
    """The base select with the dimensions' lookup tables joined and the ancestors' keys applied."""
    query = build_base_select(f, *columns)
    for dimension in tree.dimensions.values():
        for target, onclause in dimension.joins:
            query = query.join(target, onclause, isouter=True)
    keys = [tree.dimensions[name].key for name in tree.group_levels] + [product_key()]
    return query.where(*(keys[depth] == _raw_key(tree.levels[depth], key) for depth, key in enumerate(path)))


def _group_level(
    db: Session, f: PublicationFilter, tree: Tree, path: list[str], level: str, limit: int, offset: int
) -> GroupsPage:
    dimension = tree.dimensions[level]
    title = title_of(level, dimension.key, dimension.label)
    rows = _scoped(f, path, tree, dimension.key.label("k"), title.label("t")).subquery("rows")
    # One key can carry spelling variants of the same name ("Redes" / "redes "): show the trimmed one, and
    # pick it with the byte-wise "C" collation so the label does not depend on the server's locale. MIN under "C"
    # prefers the capitalized spelling ("TP-Link" over "tp-link").
    shown = func.min(func.trim(rows.c.t).collate("C"))
    ordered = (rows.c.k == NO_GROUP, func.lower(shown), rows.c.k)  # "Sin ..." last, then by name
    page = db.execute(
        select(rows.c.k, shown, func.count(), _nodes_in_level())
        .group_by(rows.c.k)
        .order_by(*ordered)
        .limit(limit)
        .offset(offset)
    ).all()
    total = _total(db, page, rows.c.k)
    nodes = []
    for raw, label, count, _total_nodes in page:
        key = _wire_key(level, raw)
        nodes.append(Node(level, key, label, count, False, _params(tree, path, level, key)))
    return GroupsPage(level, nodes, total)


def _params(tree: Tree, path: list[str], level: str, key: str) -> dict[str, str]:
    """The `/items` filters of the node `path + [key]`, ancestors included."""
    params: dict[str, str] = {}
    for depth, ancestor in enumerate(path):
        params.update(_param(tree.levels[depth], ancestor))
    params.update(_param(level, key))
    return params


def _param(level: str, key: str) -> dict[str, str]:
    """The `/items` filters of ONE level's key (written as the client sees it: text levels percent-escaped)."""
    if level in PARAM_OF:
        return {PARAM_OF[level]: key}
    if level == SUBCATEGORIA_IN_CATEGORIA:
        # `<id>|<category>`: the id holds no separator, so the first one splits it (the category may hold more)
        subcategoria, _separator, categoria = key.partition(SUBCATEGORIA_KEY_SEPARATOR)
        return {PARAM_OF["subcategoria"]: subcategoria, PARAM_OF["categoria"]: categoria}
    if level == KIND_PRODUCT:
        return {PARAM_NO_PRODUCT: "true"} if key == NO_GROUP else {PARAM_PRODUCT: key}
    if level == KIND_FAMILY:
        return {PARAM_FAMILY: key}
    return {PARAM_ITEM: key}


def _product_columns() -> list[Any]:
    label = case(
        (T.p.item_id.is_(None), literal(NO_PRODUCT_LABEL)),
        else_=func.coalesce(T.p.descripcion, T.p.codigo, literal("Producto #") + cast(T.p.item_id, String)),
    )
    return [product_key().label("k"), label.label("t"), T.p.codigo.label("codigo"), T.p.item_id.label("pid")]


def _products(
    db: Session, f: PublicationFilter, tree: Tree, path: list[str], familias: bool, limit: int, offset: int
) -> GroupsPage:
    rows = _scoped(f, path, tree, *_product_columns(), family_key().label("fk")).subquery("rows")
    if familias:
        # one row per (product, family key) first: a product is a leaf unless some family has two or more members
        per_family = (
            select(
                rows.c.k,
                func.max(rows.c.t).label("t"),
                func.max(rows.c.codigo).label("codigo"),
                func.max(rows.c.pid).label("pid"),
                func.count().label("n"),
            )
            .group_by(rows.c.k, rows.c.fk)
            .subquery("per_family")
        )
        source, count, shared = (
            per_family,
            func.sum(per_family.c.n),
            func.bool_or(per_family.c.n >= FAMILY_MIN_SIZE),
        )
        label_c, code_c, pid_c = per_family.c.t, per_family.c.codigo, per_family.c.pid
    else:
        source, count, shared = rows, func.count(), literal(False)
        label_c, code_c, pid_c = rows.c.t, rows.c.codigo, rows.c.pid
    key_c = source.c.k
    page = db.execute(
        select(key_c, func.max(label_c), func.max(code_c), func.max(pid_c), count, shared, _nodes_in_level())
        .group_by(key_c)
        .order_by(key_c == NO_GROUP, func.lower(func.max(label_c)), key_c)
        .limit(limit)
        .offset(offset)
    ).all()
    total = _total(db, page, rows.c.k)
    nodes = [
        Node(
            KIND_PRODUCT,
            key,
            label,
            int(n),
            not has_family,
            _params(tree, path, KIND_PRODUCT, key),
            producto_item_id=pid,
            codigo=codigo,
        )
        for key, label, codigo, pid, n, has_family, _total_nodes in page
    ]
    return GroupsPage(KIND_PRODUCT, nodes, total)


def _families(db: Session, f: PublicationFilter, tree: Tree, path: list[str], limit: int, offset: int) -> GroupsPage:
    rows = _scoped(
        f,
        path,
        tree,
        family_key().label("fk"),
        T.i.item_id.label("item_id"),
        T.i.family_name.label("family_name"),
        T.i.title.label("title"),
    ).subquery("rows")
    members = func.count()
    # a family is named by its family name; a lone publication by its own title, whatever its family is called
    label = case(
        (
            members >= FAMILY_MIN_SIZE,
            func.coalesce(func.max(rows.c.family_name), literal("Familia ") + rows.c.fk),
        ),
        else_=func.coalesce(func.min(rows.c.title), func.min(rows.c.item_id)),
    )
    page = db.execute(
        select(rows.c.fk, members, func.min(rows.c.item_id), label, _nodes_in_level())
        .group_by(rows.c.fk)
        .order_by(members < FAMILY_MIN_SIZE, func.lower(label), rows.c.fk)  # families first, then single MLAs
        .limit(limit)
        .offset(offset)
    ).all()
    total = _total(db, page, rows.c.fk)
    nodes = []
    for key, count, item_id, name, _total_nodes in page:
        if count >= FAMILY_MIN_SIZE:
            # two or more rows share one key only when it is a family id: the fallback key (the item id) is unique and
            # the base select never repeats a publication, so `int(key)` is safe
            nodes.append(
                Node(
                    KIND_FAMILY,
                    key,
                    name,
                    count,
                    True,
                    _params(tree, path, KIND_FAMILY, key),
                    family_id=int(key),
                )
            )
        else:
            nodes.append(
                Node(KIND_ITEM, item_id, name, count, True, _params(tree, path, KIND_ITEM, item_id), item_id=item_id)
            )
    return GroupsPage(KIND_FAMILY, nodes, total)


def _members(db: Session, f: PublicationFilter, tree: Tree, path: list[str], page: GroupsPage) -> list[tuple[str, str]]:
    """`(item_id, node key)` of every publication of the page's nodes, the key written as the node's own."""
    if page.level == KIND_FAMILY:
        return _family_members(db, f, tree, path, page)
    key = tree.dimensions[page.level].key if page.level in tree.dimensions else product_key()
    raw = {_raw_key(page.level, node.key): node.key for node in page.nodes}
    # Plain columns, straight through the connection: the ORM loading layer costs more than the rows on a big set.
    query = _scoped(f, path, tree, T.i.item_id, key.label("k")).where(key.in_(list(raw)))
    return [(item_id, raw[k]) for item_id, k in db.connection().execute(query).all()]


def _family_members(
    db: Session, f: PublicationFilter, tree: Tree, path: list[str], page: GroupsPage
) -> list[tuple[str, str]]:
    """The family level mixes two kinds of node: a family is keyed by its family id, but a lone publication is keyed
    by its MLA even when it carries a family id (the rest of its family is elsewhere), so the two are looked up
    by different columns."""
    families = [node.key for node in page.nodes if node.kind == KIND_FAMILY]
    items = [node.key for node in page.nodes if node.kind == KIND_ITEM]
    fk = family_key()
    query = _scoped(f, path, tree, T.i.item_id, fk.label("k")).where(or_(fk.in_(families), T.i.item_id.in_(items)))
    rows = db.connection().execute(query).all()  # plain columns: no ORM loading layer (see `_members`)
    lone, grouped = set(items), set(families)
    return [(item_id, item_id if item_id in lone else k) for item_id, k in rows if item_id in lone or k in grouped]


def _with_markup(
    db: Session, f: PublicationFilter, tree: Tree, path: list[str], page: GroupsPage, markup: MarkupQuery
) -> GroupsPage:
    """The page with the markup figures of its nodes: P6's computation (`compute_markups`), aggregated per node in
    Python. A small slice (a deep level) is priced by the ids of its publications; one over `ITEM_IDS_MAX` (the
    roots of a big store) by the whole filter, which is the same set or a superset, never a giant id list."""
    with gc_paused():  # tens of thousands of small objects, none in a cycle (see `gc_paused`)
        members = _members(db, f, tree, path, page)
    # `compute_markups` pauses the collector itself around the inputs and the pricing, never around the Ads provider.
    if len(members) > ITEM_IDS_MAX:
        result = compute_markups(db, markup.pricing_db, f=f, ads=markup.ads)
    else:
        result = compute_markups(db, markup.pricing_db, item_ids=[item for item, _key in members], ads=markup.ads)
    with gc_paused():
        figures = aggregate_nodes(result.items, members)
    nodes = []
    for node in page.nodes:
        found = figures.get(node.key)
        nodes.append(
            replace(node, negative_count=0, markup_min=None, markup_max=None)
            if found is None
            else replace(
                node,
                negative_count=found.negative_count,
                markup_min=found.markup_min,
                markup_max=found.markup_max,
            )
        )
    return replace(page, nodes=nodes, ads_failed=result.ads_failed)


def list_groups(
    db: Session,
    f: PublicationFilter,
    path: list[str],
    *,
    familias: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    markup: Optional[MarkupQuery] = None,
    dimension: str = DEFAULT_DIMENSION,
) -> GroupsPage:
    """The children of the node `path` names (the roots for an empty path) in the tree grouped by `dimension`, one
    page, under the filters `f`. `markup` (the caller may see margins) adds each node's markup figures."""
    tree = tree_of(dimension)
    level = level_of(tree, path, familias)
    _check_path(tree, path)
    f = resolve_pm_pairs(db, f)
    if level == KIND_FAMILY:
        page = _families(db, f, tree, path, limit, offset)
    elif level == KIND_PRODUCT:
        page = _products(db, f, tree, path, familias, limit, offset)
    else:
        page = _group_level(db, f, tree, path, level, limit, offset)
    if markup is None or not page.nodes:
        return page
    return _with_markup(db, f, tree, path, page, markup)
