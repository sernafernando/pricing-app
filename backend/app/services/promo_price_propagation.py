"""
Promo price propagation core (SDD promo-price-propagation, slice 3).

`recompute_item(db, item_id, now=None)` is the single writer-of-record that
keeps `ProductoPricing` price columns in sync with ACTIVE ML seller
promotions (`ml_item_promotions`, read cross-DB via
`ml_promotions_service.fetch_item_promotions`). Two triggers share this
same core: the panel enroll/remove hook (this slice, see
`ml_promotions_write_service`) and the periodic sync job (slice 4).

Business rules (design #937):
  1. Per target column, write the MIN price across all ACTIVE
     (candidate|started) promos of the MLAs mapping to that column.
  2. Clasica (pricelist_id=4) resolves to `precio_lista_ml`, via the
     same set-cuota single-column write pattern (setattr one column,
     no cuota cascade).
  3. Last-write-wins: a column is overwritten by a promo MIN only if its
     current origin (`producto_precio_origen`) is absent, already
     'promo', or a 'manual' edit whose `fecha` is <= the promo
     activation time (`now`). A manual edit AFTER the activation time
     freezes the column (skipped, never reverted). Implemented as a
     plain timestamp comparison (not a special-case) so slice 4's sync
     job reuses this same core unchanged.
  4. Expiry/removal: only ACTIVE promos are considered here. If a
     column ends up with no active promo, it is left FROZEN at its
     last value — never reverted.

Fail-closed: any cross-DB read failure (`fetch_item_promotions` ->
`get_mlwebhook_engine`) aborts the ENTIRE item recompute — reads for
every column are gathered BEFORE any write, so a failure partway
through never leaves a partial/wrong price.

Kill-switch: gated on `settings.PROMOS_WRITE_ENABLED` (mirrors
`ml_promotions_write_service`'s gate) — checked before any write, but
AFTER the reads, so the read failure is not masked by the kill-switch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.producto import ProductoPricing
from app.models.producto_precio_origen import ProductoPrecioOrigen, upsert_origen_promo
from app.models.publicacion_ml import PublicacionML
from app.services.ml_promotions_service import fetch_item_promotions
from app.services.pricing_columns import campo_for_pricelist

logger = logging.getLogger(__name__)


@dataclass
class ColumnOutcome:
    """Outcome of `recompute_item` for a single price column."""

    column_key: str
    status: str  # "written" | "skipped_disabled" | "skipped_no_active_promo" | "skipped_frozen_manual"
    price: Optional[float] = None
    promo_id: Optional[str] = None
    mla: Optional[str] = None


@dataclass
class RecomputeResult:
    item_id: int
    columns: List[ColumnOutcome] = field(default_factory=list)

    @property
    def written_columns(self) -> List[str]:
        return [c.column_key for c in self.columns if c.status == "written"]


def _group_mlas_by_column(db: Session, item_id: int) -> Dict[str, List[str]]:
    """Maps this product's MLAs to the `ProductoPricing` column their
    `pricelist_id` resolves to, via the centralized `pricing_columns` map
    (slice 1) — never a re-hardcoded mapping. MLAs with a missing or
    unrecognized `pricelist_id` are skipped."""
    publicaciones = (
        db.query(PublicacionML.mla, PublicacionML.pricelist_id).filter(PublicacionML.item_id == item_id).all()
    )
    by_column: Dict[str, List[str]] = {}
    for mla, pricelist_id in publicaciones:
        if pricelist_id is None:
            continue
        campo = campo_for_pricelist(pricelist_id)
        if campo is None:
            continue
        by_column.setdefault(campo, []).append(mla)
    return by_column


def _min_active_promo_for_column(mlas: List[str]) -> Optional[Dict[str, Any]]:
    """Reads ACTIVE (candidate|started) promos for every mla in `mlas` and
    returns `{price, promo_id, mla}` for the MIN priced one, or None if
    none of the MLAs currently have an active promo with a price.

    Raises whatever `fetch_item_promotions` raises (cross-DB outage) —
    the caller is responsible for `recompute_item`'s fail-closed,
    no-partial-write contract.
    """
    best: Optional[Dict[str, Any]] = None
    for mla in mlas:
        promos = fetch_item_promotions(mla, active_only=True)
        for promo in promos:
            price = promo.get("price")
            if price is None:
                continue
            if best is None or price < best["price"]:
                best = {"price": price, "promo_id": promo.get("promotion_id"), "mla": mla}
    return best


def _existing_origin(db: Session, item_id: int, column_key: str) -> Optional[ProductoPrecioOrigen]:
    return (
        db.query(ProductoPrecioOrigen)
        .filter(
            ProductoPrecioOrigen.item_id == item_id,
            ProductoPrecioOrigen.column_key == column_key,
        )
        .first()
    )


def _may_write(origin: Optional[ProductoPrecioOrigen], activation_time: datetime) -> bool:
    """Last-write-wins guard (design #937, rules #1 + #4).

    Write is allowed when the current origin is absent, already
    'promo', or a 'manual' edit whose `fecha` is <= `activation_time`.
    A 'manual' edit strictly AFTER `activation_time` blocks the write
    (frozen).
    """
    if origin is None:
        return True
    if origin.origen == "promo":
        return True
    if origin.origen == "manual":
        origin_fecha = origin.fecha
        if origin_fecha.tzinfo is None:
            origin_fecha = origin_fecha.replace(tzinfo=UTC)
        return origin_fecha <= activation_time
    return True


def _write_column(db: Session, item_id: int, campo_precio: str, precio: float) -> None:
    """Set-cuota single-column write pattern: setattr the ONE price
    column, no cuota cascade (mirrors `pricing.py::setear_precio_cuota`).
    """
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    if pricing:
        setattr(pricing, campo_precio, precio)
        pricing.fecha_modificacion = datetime.now(UTC)
    else:
        pricing = ProductoPricing(item_id=item_id, motivo_cambio="Promo price propagation")
        setattr(pricing, campo_precio, precio)
        db.add(pricing)
    db.flush()


def recompute_item(db: Session, item_id: int, *, now: Optional[datetime] = None) -> RecomputeResult:
    """Recomputes every promo-mapped price column for `item_id`.

    See module docstring for the full business-rule contract.

    Raises:
        Whatever `fetch_item_promotions` raises (cross-DB read failure)
        — propagated BEFORE any write, so the item is left untouched.
    """
    activation_time = now or datetime.now(UTC)
    result = RecomputeResult(item_id=item_id)

    by_column = _group_mlas_by_column(db, item_id)
    if not by_column:
        return result

    # Gather ALL cross-DB reads before any write: a failure here must
    # leave the item entirely untouched (fail-closed).
    column_promo: Dict[str, Optional[Dict[str, Any]]] = {
        column_key: _min_active_promo_for_column(mlas) for column_key, mlas in by_column.items()
    }

    if not settings.PROMOS_WRITE_ENABLED:
        for column_key in by_column:
            result.columns.append(ColumnOutcome(column_key=column_key, status="skipped_disabled"))
        return result

    for column_key, best in column_promo.items():
        if best is None:
            # No active promo left for this column -> FROZEN, never revert.
            result.columns.append(ColumnOutcome(column_key=column_key, status="skipped_no_active_promo"))
            continue

        origin = _existing_origin(db, item_id, column_key)
        if not _may_write(origin, activation_time):
            result.columns.append(ColumnOutcome(column_key=column_key, status="skipped_frozen_manual"))
            continue

        _write_column(db, item_id, column_key, best["price"])
        upsert_origen_promo(
            db,
            item_id,
            column_key,
            promo_id=best["promo_id"],
            mla=best["mla"],
            fecha=activation_time,
        )
        result.columns.append(
            ColumnOutcome(
                column_key=column_key,
                status="written",
                price=best["price"],
                promo_id=best["promo_id"],
                mla=best["mla"],
            )
        )

    return result
