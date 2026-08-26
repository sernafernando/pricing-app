"""Tienda Nube image normalizer — extract stage (slice 4).

Turns GBP report-78 rows into per-(EAN, image) work items, joined against
Tienda Nube products already synced into `tienda_nube_productos`.

PURE MODULE — no I/O here. This module never fetches the GBP report, never
opens a DB session, and never imports `app.core.database`. The caller (a
later slice's runner) is responsible for fetching the report rows and the
TN product rows and handing them to `extract_item_plans` as plain data.

Join key: `Código` (EAN) on the report row <-> `variant_sku` on the TN
product, compared through `normalize_gtin` (leading-zero tolerant, and
never collides two "no usable value" rows with each other — see that
function's docstring in `tn_reconciliation_service.py`).

`activo` trap: the Tienda Nube sync (`app/api/endpoints/tienda_nube.py`)
sets `activo = False` on every row before reactivating only what TN
currently returns; rows are never deleted, for audit. So `activo = False`
means "Tienda Nube no longer has this product", not "temporarily hidden".
Joining against an inactive product would queue image work for a product
TN has already removed, so this extractor only ever joins active products.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.services.tn_image_normalizer.states import ITEM_NO_SOURCE_IMAGES, ITEM_PENDING
from app.services.tn_reconciliation_service import normalize_gtin

# Local to this service on purpose: `IMAGE_KEYS` also exists in
# `app/api/endpoints/tienda_nube_reconcile.py`, but a service importing
# from the endpoint layer would be a backwards dependency.
IMAGE_KEYS = [f"image{i}" for i in range(1, 11)]

# Item states come from the package's single vocabulary (`states.py`), never
# from literals here: every stage must agree on these strings, and a drift
# between two modules surfaces as a row that silently never advances rather
# than as a failing test.
STATE_PENDING = ITEM_PENDING
STATE_NO_SOURCE_IMAGES = ITEM_NO_SOURCE_IMAGES


@dataclass(frozen=True)
class TnProductRef:
    """Minimal, plain-data view of a `TiendaNubeProducto` row.

    Deliberately not the ORM model itself — this keeps `extract.py` from
    ever needing a live `Session` or import from `app.models`, and lets
    tests build fixtures without touching the database.
    """

    product_id: int
    variant_sku: str | None
    activo: bool


@dataclass(frozen=True)
class ItemPlan:
    """One (EAN, source slot) work item to normalize, before any I/O runs."""

    ean: str
    tn_product_id: int
    source_slot: int
    source_url: str | None
    state: str


def _ordered_image_urls(gbp_row: Mapping[str, Any]) -> list[tuple[int, str]]:
    """Ordered `(1-based slot, url)` pairs for populated `image1..image10`.

    Mirrors `_gbp_images` in `tienda_nube_reconcile.py`: keeps slots in
    order, skips any slot that isn't a non-empty string after stripping,
    and never shifts the slot number of the ones that remain — slot always
    reflects the original report column, so the first image stays the
    cover regardless of which earlier slots were empty.
    """
    pairs: list[tuple[int, str]] = []
    for slot, key in enumerate(IMAGE_KEYS, start=1):
        value = gbp_row.get(key)
        if isinstance(value, str) and value.strip():
            pairs.append((slot, value))
    return pairs


def _build_active_product_index(products: Iterable[TnProductRef]) -> dict[str, TnProductRef]:
    """Index active products by normalized `variant_sku`.

    Products whose normalized SKU is a sentinel (blank/None/non-numeric)
    are never indexed — a sentinel is never equal to anything, including
    another sentinel, so it could never be looked up again regardless.
    """
    index: dict[str, TnProductRef] = {}
    for product in products:
        if not product.activo:
            continue
        normalized = normalize_gtin(product.variant_sku)
        if not isinstance(normalized, str):
            continue
        index[normalized] = product
    return index


def extract_item_plans(
    report_rows: Sequence[Mapping[str, Any]],
    tn_products: Sequence[TnProductRef],
) -> list[ItemPlan]:
    """Join GBP report-78 rows to active Tienda Nube products.

    Pure function: `report_rows` and `tn_products` are already-fetched
    plain data (dicts / `TnProductRef`), never a `Session` and never
    fetched here.

    - A report EAN with no active TN match produces no rows.
    - A matching product with populated image slots produces one
      `ItemPlan` per slot, in report order, `source_slot` preserved.
    - A matching product with zero usable image slots produces exactly one
      reviewable `ItemPlan` marked `no_source_images` (never silently
      dropped — a human decision needs to see it).
    """
    active_by_ean = _build_active_product_index(tn_products)
    plans: list[ItemPlan] = []

    for row in report_rows:
        ean = normalize_gtin(row.get("Código"))
        if not isinstance(ean, str):
            continue

        product = active_by_ean.get(ean)
        if product is None:
            continue

        image_pairs = _ordered_image_urls(row)
        if not image_pairs:
            plans.append(
                ItemPlan(
                    ean=ean,
                    tn_product_id=product.product_id,
                    source_slot=0,
                    source_url=None,
                    state=STATE_NO_SOURCE_IMAGES,
                )
            )
            continue

        for slot, url in image_pairs:
            plans.append(
                ItemPlan(
                    ean=ean,
                    tn_product_id=product.product_id,
                    source_slot=slot,
                    source_url=url,
                    state=STATE_PENDING,
                )
            )

    return plans
