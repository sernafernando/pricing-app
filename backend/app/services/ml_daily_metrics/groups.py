"""The "Agrupado" view of the Métricas ML board (ODD `metricas-ml-vista-agrupada`):
the board's (product, MLA) pairs summed by a DIMENSION -- marca, categoría,
subcategoría, tienda or PM.

The key and label of every pair are COLUMNS of the board's own pair table
(`board_pair_agg`, computed once per request with the few small lookup joins the
dimension needs), so grouping is a plain GROUP BY over the products that
survive the row filters, and opening a group is a plain `gkey = :key` filter
the planner can estimate. No table of its own beyond that one.

Dimension semantics (one group KEY per pair, `NO_GROUP` for "Sin ..."):

- marca / categoría: the value trimmed and upper-cased, so `Epson` and `EPSON`
  are ONE group (the filters match case-insensitively too); the label is the
  spelling that sorts last, like the facet lists.
- subcategoría: the id; the label is the name in `subcategorias_grupos`.
- tienda: the PUBLICATION's current `mlp_official_store_id`. Ids sharing a
  `clave` in `ml_tiendas_oficiales` are ONE group (`c:<clave>`, labelled with
  the first active store of the clave by `orden`); an id with no row is its own
  group (`s:<id>`, "Tienda <id>"). Each sale belongs to one publication, so a
  product selling in two stores adds to each only what that store sold.
- PM: the PM of the product's (marca, categoría) pair in `marcas_pm`, matched
  upper-case like the PM filter. A pair listed twice differing only in case
  resolves to the lowest user id: one PM per pair, so no product counts twice.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional

from sqlalchemy import String, case, cast, func, literal, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.producto import ProductoERP
from app.models.usuario import Usuario

DIMENSIONS = ("marca", "categoria", "subcategoria", "tienda", "pm")
# Prefixes of a store group's key: `c:<clave>` for the ids sharing a clave,
# `s:<id>` for a store with none. The ONE place they are written and read.
CLAVE_KEY_PREFIX = "c:"
STORE_KEY_PREFIX = "s:"
# The key of the "Sin ..." group. Reserved: a real value can never be this.
NO_GROUP = "__none__"
NO_LABELS = {
    "marca": "Sin marca",
    "categoria": "Sin categoría",
    "subcategoria": "Sin subcategoría",
    "tienda": "Sin tienda",
    "pm": "Sin PM",
}
# The per-pair sums every group adds up (the board row's, by name).
SUM_COLUMNS = (
    "units",
    "gross",
    "tg",
    "mtg",
    "costo",
    "prev_units",
    "prev_gross",
    "prev_tg",
    "prev_mtg",
    "prev_costo",
    "w3d",
    "w7d",
    "w15d",
    "w30d",
    "u24",
)


class Dimension(NamedTuple):
    key: ColumnElement
    label: ColumnElement
    # `(target, onclause)` pairs to LEFT JOIN onto the pair source.
    joins: list


def _text_dimension(column: ColumnElement) -> Dimension:
    normalized = func.upper(func.trim(func.coalesce(column, "")))
    return Dimension(case((normalized == "", literal(NO_GROUP)), else_=normalized), column, [])


def _subcategoria_dimension(subcategoria_id: Any) -> Dimension:
    names = aliased(SubcategoriaGrupo)
    key = case((subcategoria_id.is_(None), literal(NO_GROUP)), else_=cast(subcategoria_id, String))
    return Dimension(key, names.nombre_subcategoria, [(names, names.subcat_id == subcategoria_id)])


def _tienda_dimension(store_id: Any) -> Dimension:
    stores = aliased(MlTiendaOficial)
    own = case(
        (
            stores.clave.isnot(None) & (func.trim(stores.clave) != ""),
            literal(CLAVE_KEY_PREFIX) + func.trim(stores.clave),
        ),
        else_=literal(STORE_KEY_PREFIX) + cast(stores.store_id, String),
    )
    # Every store row carries the name of its clave's first active store.
    named = (
        select(
            stores.store_id.label("store_id"),
            own.label("gkey"),
            func.first_value(stores.nombre)
            .over(partition_by=own, order_by=(stores.activa.desc(), stores.orden, stores.store_id))
            .label("nombre"),
        )
    ).subquery("store_names")
    key = case(
        (store_id.is_(None), literal(NO_GROUP)),
        else_=func.coalesce(named.c.gkey, literal(STORE_KEY_PREFIX) + cast(store_id, String)),
    )
    return Dimension(key, named.c.nombre, [(named, named.c.store_id == store_id)])


def _pm_dimension(marca: Any, categoria: Any) -> Dimension:
    pairs = (
        select(
            func.upper(MarcaPM.marca).label("marca"),
            func.upper(MarcaPM.categoria).label("categoria"),
            func.min(MarcaPM.usuario_id).label("usuario_id"),
        )
        .where(MarcaPM.usuario_id.isnot(None))
        .group_by(func.upper(MarcaPM.marca), func.upper(MarcaPM.categoria))
    ).subquery("pm_pairs")
    pms = aliased(Usuario)
    key = case((pairs.c.usuario_id.is_(None), literal(NO_GROUP)), else_=cast(pairs.c.usuario_id, String))
    return Dimension(
        key,
        pms.nombre,
        [
            (pairs, (pairs.c.marca == func.upper(marca)) & (pairs.c.categoria == func.upper(categoria))),
            (pms, pms.id == pairs.c.usuario_id),
        ],
    )


def dimension_of(name: str, *, marca: Any, categoria: Any, subcategoria_id: Any, store_id: Any) -> Dimension:
    """The key/label/joins of dimension `name`, over the pair's own columns
    (each a column expression of whatever the caller selects from)."""
    if name == "marca":
        return _text_dimension(marca)
    if name == "categoria":
        return _text_dimension(categoria)
    if name == "subcategoria":
        return _subcategoria_dimension(subcategoria_id)
    if name == "tienda":
        return _tienda_dimension(store_id)
    if name == "pm":
        return _pm_dimension(marca, categoria)
    raise ValueError(f"Not a dimension: {name!r} (expected one of {DIMENSIONS})")


def title_of(name: str, key: ColumnElement, label: ColumnElement) -> ColumnElement:
    """The group's display name: its label, else a readable fallback for a key
    whose lookup row is missing (a subcategory not in the names table, a store
    with no row, a PM whose user is gone); the fixed "Sin ..." for no group."""
    fallback: Optional[ColumnElement] = None
    if name == "subcategoria":
        fallback = literal("Subcategoría #") + key
    elif name == "tienda":
        fallback = literal("Tienda ") + func.substr(key, len(STORE_KEY_PREFIX) + 1)
    elif name == "pm":
        fallback = literal("PM #") + key
    shown = func.coalesce(label, fallback) if fallback is not None else label
    return case((key == NO_GROUP, literal(NO_LABELS[name])), else_=shown)


def grouped_pairs(joined: Any, fp: Any, stock: Any) -> Any:
    """One row per (product, MLA) pair of `joined` (the surviving products'
    pairs, `fp` their columns, group `gkey` and `glabel` among them) with its
    sums and its product's `stock`, counted ONCE per (group, product):
    `first_in_group` marks the single pair that carries it."""
    source = joined.outerjoin(stock, stock.c.item_id == fp.c.product)
    inner = (
        select(
            fp.c.gkey,
            fp.c.glabel,
            fp.c.product,
            fp.c.mla,
            *(fp.c[column] for column in SUM_COLUMNS),
            fp.c.last_day,
            fp.c.last_at,
            fp.c.start_day,
            stock.c.stock.label("stock"),
        )
        .select_from(source)
        .subquery("group_pairs_raw")
    )
    first = func.row_number().over(partition_by=(inner.c.gkey, inner.c.product), order_by=inner.c.mla) == 1
    return select(*inner.c, case((first, 1), else_=0).label("first_in_group")).subquery("group_pairs")


def stock_table() -> Any:
    """The ERP product table aliased for the per-product stock join."""
    return ProductoERP.__table__.alias("group_stock")


__all__ = [
    "DIMENSIONS",
    "NO_GROUP",
    "NO_LABELS",
    "SUM_COLUMNS",
    "Dimension",
    "dimension_of",
    "grouped_pairs",
    "stock_table",
    "title_of",
]
