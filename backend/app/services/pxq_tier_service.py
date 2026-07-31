"""Service-layer creation/validation for `MlPxqTier` rows.

Max 5 tiers per publication is enforced HERE (422), not as a DB constraint
(design D-table note). `cantidad_minima > 1` is validated here too, ahead of
the DB CheckConstraint, so the caller gets a clean 422 instead of an
`IntegrityError`.

This module must NEVER import `ProductoPricing` — PxQ tiers are additional
quantity prices that never touch the base price (enforced by an AST
import-scan test).
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ml_pxq_tier import ESTADO_INCOMPLETO, MlPxqTier
from app.models.publicacion_ml import PublicacionML

MAX_TIERS_PER_PUBLICATION = 5


def create_pxq_tier(
    db: Session,
    publicacion_ml_id: int,
    item_id: str,
    cantidad_minima: int,
    precio_unitario: float,
    usuario_id: int,
    costo_envio_total: Optional[float] = None,
    ml_price_id: Optional[str] = None,
) -> MlPxqTier:
    """Creates a `MlPxqTier` row after service-layer validation.

    Raises:
        HTTPException(422): `cantidad_minima <= 1`, or the publication
            already has `MAX_TIERS_PER_PUBLICATION` tiers.
    """
    if cantidad_minima <= 1:
        raise HTTPException(
            status_code=422,
            detail=f"cantidad_minima must be > 1 (got {cantidad_minima})",
        )

    # Lock the publication row before counting. The five-tier ceiling is a
    # product rule, so it lives here rather than in a DB constraint — but a
    # bare count() is a read followed by a write, and two concurrent creates
    # on a publication holding four tiers would both read four, both pass, and
    # leave six rows. MercadoLibre would then reject the whole array on PR 3's
    # write path. Serializing per publication closes that window; on SQLite
    # (tests) the FOR UPDATE is a harmless no-op.
    db.query(PublicacionML.id).filter(PublicacionML.id == publicacion_ml_id).with_for_update().first()

    existing_count = db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion_ml_id).count()
    if existing_count >= MAX_TIERS_PER_PUBLICATION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"publicacion_ml_id={publicacion_ml_id} already has {existing_count} tiers; "
                f"max is {MAX_TIERS_PER_PUBLICATION}"
            ),
        )

    tier = MlPxqTier(
        publicacion_ml_id=publicacion_ml_id,
        item_id=item_id,
        cantidad_minima=cantidad_minima,
        precio_unitario=precio_unitario,
        costo_envio_total=costo_envio_total,
        ml_price_id=ml_price_id,
        estado=ESTADO_INCOMPLETO,
        usuario_id=usuario_id,
    )
    db.add(tier)
    db.flush()
    return tier
