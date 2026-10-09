"""The Historial tab: what changed in a publication, from `ml_change_log` (design §3.5).

One page merges the rows keyed by the item (the item itself, its sub-resources and its product links, all with
`item_id`) with the rows of its user product (`user_product`, `stock`, `replenishment`) and its family, which belong
to no single item (the store writes them with `item_id` NULL) and are found by `(resource_type, entity_id)`; the
`item_id IS NULL` guard keeps a row that ever carried both keys from being read by two branches. Each branch is a keyset scan of its own index
(`ix_ml_change_log_item`, `ix_ml_change_log_entity`) bounded by the page size, so the merge reads at most
`3 x page` rows however long the log is; the outer query orders them `observed_at DESC, id DESC`.

Each entry is one log row split into BUSINESS lines (what a person looks at: prices, status, stock, title, promotions,
the product link) and TECHNICAL ones (everything else, kept for "ver todo"), one line per changed field. `split` is the
pure rule: an allowlist of paths per resource, written against the paths the diff engine really produces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.ml_publications.view import events_view, listing

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
STATEMENT_TIMEOUT = "3s"

# Resources whose log rows are keyed by the item's user product, and the one keyed by its family.
USER_PRODUCT_RESOURCES = ("user_product", "stock", "replenishment")
FAMILY_RESOURCE = "family"


@dataclass(frozen=True)
class Change:
    """One changed field: `old`/`new` are `None` on the side that does not exist (an added or removed field)."""

    path: str
    old: Any = None
    new: Any = None
    label_key: Optional[str] = None  # set on business lines only
    label: Optional[str] = None  # Spanish, the label of `label_key`


# ── The rule: which paths are business, per resource ─────────────────────────────────────────────────────────


def _rules(*pairs: tuple[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern), key) for pattern, key in pairs)


BUSINESS_RULES: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "item": _rules(
        (r"^price$", "price"),
        (r"^base_price$", "base_price"),
        (r"^original_price$", "original_price"),
        (r"^status$", "status"),
        (r"^sub_status(\[|$)", "sub_status"),
        (r"^available_quantity$", "available_quantity"),
        (r"^listing_type_id$", "listing_type"),
        (r"^title$", "title"),
        (r"^tags(\[|$)", "tags"),
        (r"^shipping\.logistic_type$", "logistic_type"),
        (r"^catalog_listing$", "catalog_listing"),
        (r"^sale_terms\[INSTALLMENTS_CAMPAIGN\]", "installments_campaign"),
    ),
    "prices": _rules((r"^prices\[[^\]]+\](\.(amount|regular_amount))?$", "price_channel")),
    "sale_price": _rules(
        (r"^amount$", "sale_price"),
        (r"^regular_amount$", "regular_price"),
        (r"^metadata\.promotion_type$", "promotion_type"),
    ),
    "promotions": _rules(
        (r"^\[[^\]]+\]$", "promotion"),
        (r"^\[[^\]]+\]\.status$", "promotion_status"),
        (r"^\[[^\]]+\]\.price$", "promotion_price"),
    ),
    "stock": _rules((r"^locations(\[[^\]]+\](\.quantity)?)?$", "stock_location")),
    "product_link": _rules((r"^producto_item_id$", "product_link")),
    "competition": _rules((r"^status$", "competition_status"), (r"^price_to_win$", "price_to_win")),
}

LABELS: dict[str, str] = {
    "price": "Precio",
    "base_price": "Precio base",
    "original_price": "Precio original",
    "status": "Estado",
    "sub_status": "Subestado",
    "available_quantity": "Stock disponible",
    "listing_type": "Tipo de publicación",
    "title": "Título",
    "tags": "Etiquetas",
    "logistic_type": "Tipo de logística",
    "catalog_listing": "Publicación de catálogo",
    "installments_campaign": "Campaña de cuotas",
    "price_channel": "Precio por canal",
    "sale_price": "Precio de venta",
    "regular_price": "Precio regular",
    "promotion_type": "Tipo de promoción",
    "promotion": "Promoción",
    "promotion_status": "Estado de la promoción",
    "promotion_price": "Precio de la promoción",
    "stock_location": "Stock por ubicación",
    "product_link": "Producto vinculado",
    "competition_status": "Competencia de catálogo",
    "price_to_win": "Precio para ganar",
}


def _label_key(resource_type: str, path: str) -> Optional[str]:
    for pattern, key in BUSINESS_RULES.get(resource_type, ()):
        if pattern.search(path):
            return key
    return None


def split(resource_type: str, changes: Sequence[Mapping[str, Any]]) -> tuple[list[Change], list[Change]]:
    """`(business, technical)` lines of one log row's `changes`, each in the row's own order. The same path means a
    business field only on the resource that owns it (`status` is the item's on `item`, the competition's on
    `competition`); a resource with no rule has only technical lines."""
    business: list[Change] = []
    technical: list[Change] = []
    for stored in changes:
        path = str(stored.get("p", ""))
        key = _label_key(resource_type, path)
        if key is None:
            technical.append(Change(path, stored.get("old"), stored.get("new")))
        else:
            business.append(Change(path, stored.get("old"), stored.get("new"), key, LABELS[key]))
    return business, technical


# ── The page ─────────────────────────────────────────────────────────────────────────────────────────────────

_COLUMNS = "id, resource_type, kind, observed_at, changes"
_AFTER = "AND (observed_at, id) < (:cursor_at, :cursor_id)"


def _page_sql(after: str) -> str:
    def branch(where: str) -> str:
        return (
            f"(SELECT {_COLUMNS} FROM ml_change_log WHERE {where} {after} "
            "ORDER BY observed_at DESC, id DESC LIMIT :row_limit)"
        )

    users = ", ".join(f"'{name}'" for name in USER_PRODUCT_RESOURCES)
    branches = " UNION ALL ".join(
        (
            branch("item_id = :item_id"),
            branch(f"resource_type IN ({users}) AND entity_id = :user_product_id AND item_id IS NULL"),
            branch(f"resource_type = '{FAMILY_RESOURCE}' AND entity_id = :family_id AND item_id IS NULL"),
        )
    )
    return f"SELECT {_COLUMNS} FROM ({branches}) page ORDER BY observed_at DESC, id DESC LIMIT :row_limit"


PAGE_SQL = _page_sql("")
PAGE_SQL_AFTER = _page_sql(_AFTER)


def page_sql(after: bool = False) -> str:
    """The merged page statement; `after` adds the keyset condition (a page past the first)."""
    return PAGE_SQL_AFTER if after else PAGE_SQL


@dataclass(frozen=True)
class HistoryPage:
    entries: list[dict[str, Any]]
    next_cursor: Optional[str]


def _line_out(line: Change) -> dict[str, Any]:
    return {"path": line.path, "label_key": line.label_key, "label": line.label, "old": line.old, "new": line.new}


def _entry_out(row: Any) -> dict[str, Any]:
    business, technical = split(row["resource_type"], row["changes"] or [])
    return {
        "id": row["id"],
        "observed_at": row["observed_at"],
        "resource_type": row["resource_type"],
        "kind": row["kind"],
        "business": [_line_out(line) for line in business],
        "technical": [_line_out(line) for line in technical],
    }


def list_history(
    db: Session,
    item_id: str,
    *,
    cursor: Optional[tuple[datetime, int]] = None,
    limit: int = DEFAULT_LIMIT,
) -> Optional[HistoryPage]:
    """One page of the publication's change log, newest first; `None` when the item is not a publication."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    listing.bound(db, STATEMENT_TIMEOUT)
    ref = events_view.item_ref(db, item_id)
    if ref is None:
        return None
    params: dict[str, Any] = {
        "item_id": item_id,
        "user_product_id": ref.user_product_id,
        "family_id": None if ref.family_id is None else str(ref.family_id),
        "row_limit": limit + 1,  # one more row says whether another page exists, without a count
    }
    if cursor is not None:
        params.update(cursor_at=cursor[0], cursor_id=cursor[1])
    rows = db.execute(text(page_sql(cursor is not None)), params).mappings().all()
    page = rows[:limit]
    more = events_view.encode_cursor(page[-1]["observed_at"], page[-1]["id"]) if len(rows) > limit else None
    return HistoryPage([_entry_out(row) for row in page], more)
