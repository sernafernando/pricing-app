"""Service-layer creation/validation for `MlPxqTier` rows.

Max 5 tiers per publication is enforced HERE (422), not as a DB constraint
(design D-table note). The `cantidad_minima` floor is validated here too,
ahead of the DB CheckConstraint, so the caller gets a clean 422 instead of an
`IntegrityError`.

That floor is `>= 1` on BOTH write paths — `create_pxq_tier` and
`update_pxq_tier` — and the two must not drift apart. It matches
`ck_ml_pxq_tier_cantidad_minima_ge_1`, which carries the reasoning: a one-unit
tier is what turns on "Venta para negocios" on MercadoLibre. A path that
accepted a quantity the other refused would let the import write a row the
operator could not then edit.

This module must NEVER import `ProductoPricing` — PxQ tiers are additional
quantity prices that never touch the base price (enforced by an AST
import-scan test).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ml_pxq_tier import ESTADO_INCOMPLETO, MlPxqTier
from app.models.publicacion_ml import PublicacionML

# Single source of truth lives in the pure diff module, which enforces the
# same ceiling on the array it builds.
from app.services.pxq_diff import MAX_TIERS as MAX_TIERS_PER_PUBLICATION

# Money columns are Numeric(14, 2). Accepting a bare float and letting the
# driver convert means 500.10 stops being 500.10 — invisible on SQLite, and in
# Postgres it only surfaces when a sum of tiers refuses to reconcile. Going
# through str() is what keeps the decimal value the caller wrote.
Money = Union[Decimal, float, int, str]


# NOT consolidated with `pxq_diff._to_decimal`, deliberately. The two bodies
# are behaviourally identical, but their declared input domains are not: this
# module's `Money` admits `str` (see the comment above) and `pxq_diff.Money`
# does not. Importing that one and feeding it a `str` would trade a visible
# duplicate for an invisible type-contract violation — a worse drift class
# than the one being removed. The honest fix is to widen `pxq_diff.Money`
# first, and `pxq_diff` is out of scope for this change.
# ponytail: consolidate onto pxq_diff._to_decimal once pxq_diff.Money admits str
def _to_decimal(value: Money) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def create_pxq_tier(
    db: Session,
    publicacion_ml_id: int,
    item_id: str,
    cantidad_minima: int,
    precio_unitario: Money,
    usuario_id: int,
    costo_envio_total: Optional[Money] = None,
    ml_price_id: Optional[str] = None,
    cantidad_sincronizada: Optional[int] = None,
    precio_sincronizado: Optional[Money] = None,
) -> MlPxqTier:
    """Creates a `MlPxqTier` row after service-layer validation.

    `cantidad_sincronizada`/`precio_sincronizado` are the ML-confirmed
    SNAPSHOT and both default to `None`, which is what every manually created
    tier gets: it has never been confirmed by MercadoLibre, so there is
    nothing to have diverged from. They exist for the IMPORT path
    (`adopt-live`), where the row's values ARE the values MercadoLibre just
    reported, in the same operation — so the snapshot is correct by
    construction and there is no prior value to overwrite. An ordinary edit
    must never advance them; see `update_pxq_tier`.

    Raises:
        HTTPException(422): `cantidad_minima < 1`; exactly one half of the
            snapshot pair supplied; the publication does not exist or already
            has `MAX_TIERS_PER_PUBLICATION` tiers; `item_id` does not match
            the publication; duplicate `cantidad_minima`.
    """
    # `< 1`, not `<= 1`. A tier of ONE unit is legal here on purpose: it is
    # what makes the publication appear as "Venta para negocios" on
    # MercadoLibre, and ML accepts and holds it in production despite its own
    # documentation saying `min_purchase_unit` must be greater than 1. The full
    # reasoning, and the evidence, live on the CheckConstraint in
    # `app/models/ml_pxq_tier.py` -- this validation only mirrors it so the
    # caller gets a 422 instead of an IntegrityError surfacing as a 500.
    if cantidad_minima < 1:
        raise HTTPException(
            status_code=422,
            detail=f"cantidad_minima must be >= 1 (got {cantidad_minima})",
        )

    # Both-or-neither. `pxq_diff.DesiredTier.has_snapshot` requires BOTH
    # columns to be non-NULL, so a row carrying only one half reads as "never
    # synced" — and that is not inert: `local_changed` is then unconditionally
    # True and `live_changed` unconditionally False, so every later sync
    # classifies the row as "we edited it, ML did not" and pushes the local
    # value over whatever MercadoLibre holds, permanently. Checked here, ahead
    # of the lock, because it is a caller bug that needs no DB state to detect.
    if (cantidad_sincronizada is None) != (precio_sincronizado is None):
        raise HTTPException(
            status_code=422,
            detail=(
                "cantidad_sincronizada and precio_sincronizado must be supplied together "
                "or not at all; half a snapshot reads as no snapshot and would make this "
                "tier silently overwrite MercadoLibre on every later sync"
            ),
        )

    # Lock the publication row before counting. The five-tier ceiling is a
    # product rule, so it lives here rather than in a DB constraint — but a
    # bare count() is a read followed by a write, and two concurrent creates
    # on a publication holding four tiers would both read four, both pass, and
    # leave six rows. MercadoLibre would then reject the whole array on PR 3's
    # write path. Serializing per publication closes that window; on SQLite
    # (tests) the FOR UPDATE is a harmless no-op.
    publicacion = (
        db.query(PublicacionML.id, PublicacionML.mla)
        .filter(PublicacionML.id == publicacion_ml_id)
        .with_for_update()
        .first()
    )
    if publicacion is None:
        # No row means no lock was taken, so the window above stays open for
        # exactly this case. Failing here also turns what would otherwise be an
        # FK IntegrityError at flush into the clean 422 this service promises.
        raise HTTPException(
            status_code=422,
            detail=f"publicacion_ml_id={publicacion_ml_id} does not exist",
        )

    existing_count = db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion_ml_id).count()
    if existing_count >= MAX_TIERS_PER_PUBLICATION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"publicacion_ml_id={publicacion_ml_id} already has {existing_count} tiers; "
                f"max is {MAX_TIERS_PER_PUBLICATION}"
            ),
        )

    # `item_id` is the MLA denormalized off the publication, and PR 3 keys the
    # live-vs-mirror diff on it. A row claiming a different MLA than its own
    # publication would send that diff at the wrong listing, so it is checked
    # against the row already in hand rather than trusted.
    if item_id != publicacion.mla:
        raise HTTPException(
            status_code=422,
            detail=(
                f"item_id={item_id!r} does not match publicacion_ml_id={publicacion_ml_id} "
                f"(expected {publicacion.mla!r})"
            ),
        )

    # Same reason as the count above, and inside the same locked window: the
    # unique constraint exists, but reaching it means an IntegrityError at
    # flush, which an endpoint surfaces as a 500 where this service promises
    # a 422.
    duplicate = (
        db.query(MlPxqTier.id)
        .filter(
            MlPxqTier.publicacion_ml_id == publicacion_ml_id,
            MlPxqTier.cantidad_minima == cantidad_minima,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=422,
            detail=(f"publicacion_ml_id={publicacion_ml_id} already has a tier with cantidad_minima={cantidad_minima}"),
        )

    tier = MlPxqTier(
        publicacion_ml_id=publicacion_ml_id,
        item_id=item_id,
        cantidad_minima=cantidad_minima,
        precio_unitario=_to_decimal(precio_unitario),
        costo_envio_total=(None if costo_envio_total is None else _to_decimal(costo_envio_total)),
        ml_price_id=ml_price_id,
        cantidad_sincronizada=cantidad_sincronizada,
        precio_sincronizado=(None if precio_sincronizado is None else _to_decimal(precio_sincronizado)),
        estado=ESTADO_INCOMPLETO,
        usuario_id=usuario_id,
    )
    db.add(tier)
    db.flush()
    return tier


def _get_tier_or_404(db: Session, tier_id: int) -> MlPxqTier:
    tier = db.get(MlPxqTier, tier_id)
    if tier is None:
        raise HTTPException(status_code=404, detail=f"tier_id={tier_id} does not exist")
    return tier


def update_pxq_tier(
    db: Session,
    tier_id: int,
    *,
    cantidad_minima: Optional[int] = None,
    precio_unitario: Optional[Money] = None,
    costo_envio_total: Optional[Money] = None,
) -> MlPxqTier:
    """Updates a `MlPxqTier` row's quantity/price fields.

    Deliberately never touches `cantidad_sincronizada` / `precio_sincronizado`.
    Those columns are the snapshot of what MercadoLibre last confirmed — the
    shared base the write path uses to tell "the user changed this" apart
    from "ML changed this" (a three-way merge). If an edit advanced them, the
    edit would look, to the next sync, exactly like nobody had changed
    anything, and that sync would silently overwrite whatever value ML holds.
    Only a confirmed write (`pxq_confirm`) may advance the snapshot.

    Only fields explicitly passed (not None) are updated; omit a field to
    leave it untouched.

    Raises:
        HTTPException(404): no tier with `tier_id`.
        HTTPException(422): `cantidad_minima < 1`, or the new
            `cantidad_minima` collides with another tier on the same
            publication.
    """
    tier = _get_tier_or_404(db, tier_id)

    if cantidad_minima is not None:
        # Same floor as `create_pxq_tier`, and it has to stay the same one. A
        # tier of ONE unit is what makes the publication appear as "Venta para
        # negocios" on MercadoLibre; the reasoning and the production evidence
        # live on `ck_ml_pxq_tier_cantidad_minima_ge_1`.
        #
        # This path refusing `1` while create and the import ACCEPT it was not
        # a harmless inconsistency: `adopt-live` writes one-unit rows, the
        # panel renders them, and the operator correcting one by hand would
        # have hit a 422 about a row the system itself had just imported.
        if cantidad_minima < 1:
            raise HTTPException(
                status_code=422,
                detail=f"cantidad_minima must be >= 1 (got {cantidad_minima})",
            )
        duplicate = (
            db.query(MlPxqTier.id)
            .filter(
                MlPxqTier.publicacion_ml_id == tier.publicacion_ml_id,
                MlPxqTier.cantidad_minima == cantidad_minima,
                MlPxqTier.id != tier_id,
            )
            .first()
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"publicacion_ml_id={tier.publicacion_ml_id} already has a tier "
                    f"with cantidad_minima={cantidad_minima}"
                ),
            )
        tier.cantidad_minima = cantidad_minima

    # D3 (slice B): `costo_envio_fetched_at` tracks freshness of the shipping
    # VALUE, not who wrote it. A write to `precio_unitario`/`cantidad_minima`
    # invalidates it -- shipping depends on both, so any previously
    # fetched/stamped value is now stale and must trigger a re-fetch on the
    # next open (`pxq_markup_service.refresh_tier_shipping`). Order matters:
    # this branch (invalidate) runs BEFORE the `costo_envio_total` branch
    # below (stamp), so a single PATCH carrying BOTH an invalidating field
    # and a manual `costo_envio_total` ends up STAMPED, not NULL -- the
    # manual value for the NEW price/quantity wins deterministically.
    if precio_unitario is not None or cantidad_minima is not None:
        tier.costo_envio_fetched_at = None

    if precio_unitario is not None:
        tier.precio_unitario = _to_decimal(precio_unitario)

    if costo_envio_total is not None:
        tier.costo_envio_total = _to_decimal(costo_envio_total)
        # A MANUAL write still stamps `now()` -- the operator does not own
        # this field. Their value is valid for exactly the same 24h TTL the
        # auto-fetch honors, and after that the auto-fetch wins over it, same
        # as it would over its own stale fetch. Never left NULL by a manual
        # write: NULL means "never fetched/invalidated," which a manual
        # write is neither.
        tier.costo_envio_fetched_at = datetime.now(timezone.utc)

    db.flush()
    return tier


def delete_pxq_tier(db: Session, tier_id: int) -> None:
    """Deletes a `MlPxqTier` row.

    This removes the LOCAL mirror row only — it does not, by itself, remove
    the tier from MercadoLibre. The array-replace diff (PR 3) reads from this
    table, so a deleted row simply stops being sent on the next sync; ML still
    holds the old tier until that sync runs. A row that already had an
    `ml_price_id` therefore leaves a sync pending after this call returns.

    Raises:
        HTTPException(404): no tier with `tier_id`.
    """
    tier = _get_tier_or_404(db, tier_id)
    db.delete(tier)
    db.flush()
