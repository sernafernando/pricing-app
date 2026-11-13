"""Which brands every brand option list offers: the ONE shared visibility rule.

A brand is offered iff it has at least one product in stock (`ProductoERP.stock > 0`,
the notion `/marcas?con_stock=true` already uses) OR an admin added it to the
exception list (`MarcaVisibleExcepcion`, Admin panel). The sales screens (Métricas
ML, the old Métricas and Ventas ML) also offer a brand that sold in the period and
filters being viewed: they pass those brands as `sold`.

Only the OPTIONS are hidden: rows, totals and history keep every brand, and a
brand the request already filters by (`keep`) stays in the list so its chip still
shows (a URL or saved filter naming a hidden brand keeps working).

Brands are compared by `brand_key` (`upper(trim(...))`), the key the product
facets and the PM pairs use, so "Epson" and "EPSON " are the same brand whatever
table the option list reads them from.

Cost: ONE grouped statement per request (the distinct brands with stock, plus the
exception list), then a set lookup per option; never a query per brand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, FrozenSet, Iterable, List, Optional, TypeVar

from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.producto import ProductoERP

T = TypeVar("T")


def brand_key(marca: Optional[str]) -> str:
    """The comparison key of a brand: trimmed, upper-cased, `""` for none."""
    return (marca or "").strip().upper()


def _key_sql(column: object) -> object:
    return func.upper(func.trim(func.coalesce(column, "")))


def visible_brand_keys_statement():
    """The keys of the brands that are visible without any sales context: with stock, or in the exception list."""
    with_stock = select(_key_sql(ProductoERP.marca).label("k")).where(ProductoERP.stock > 0).group_by("k")
    exceptions = select(_key_sql(MarcaVisibleExcepcion.marca).label("k"))
    return union(with_stock, exceptions)


@dataclass(frozen=True)
class BrandVisibility:
    """The visible brand keys of one request; filter as many option lists as needed with it."""

    keys: FrozenSet[str]

    def is_visible(self, marca: Optional[str], extra: FrozenSet[str] = frozenset()) -> bool:
        key = brand_key(marca)
        return bool(key) and (key in self.keys or key in extra)

    def filter(
        self,
        options: Iterable[T],
        keep: Iterable[Optional[str]] = (),
        sold: Iterable[Optional[str]] = (),
        marca_of: Optional[Callable[[T], Optional[str]]] = None,
    ) -> List[T]:
        """`options` without the hidden brands, order kept. `keep`: the brands the request already selects
        (they stay); `sold`: brands with sales in the viewed period (sales screens only). `marca_of` reads the
        brand of an option that is not a plain string (a dict row, for instance)."""
        extra = frozenset(brand_key(m) for m in (*keep, *sold) if brand_key(m))
        read = marca_of or (lambda option: option)  # type: ignore[assignment, return-value]
        return [option for option in options if self.is_visible(read(option), extra)]  # type: ignore[arg-type]


def brand_visibility(db: Session) -> BrandVisibility:
    """The request's `BrandVisibility`: one statement."""
    return BrandVisibility(keys=frozenset(k for (k,) in db.execute(visible_brand_keys_statement()) if k))


def filter_visible_brands(
    db: Session,
    options: Iterable[T],
    keep: Iterable[Optional[str]] = (),
    sold: Iterable[Optional[str]] = (),
    marca_of: Optional[Callable[[T], Optional[str]]] = None,
) -> List[T]:
    """Shortcut for one option list: `brand_visibility(db).filter(...)`."""
    return brand_visibility(db).filter(options, keep=keep, sold=sold, marca_of=marca_of)


__all__ = [
    "BrandVisibility",
    "brand_key",
    "brand_visibility",
    "filter_visible_brands",
    "visible_brand_keys_statement",
]
