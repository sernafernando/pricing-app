"""`ml_pxq_tier`: local mirror of MercadoLibre PxQ (price-by-quantity,
wholesale) tiers for a publication.

This table is the sole source of truth for the array-replace diff against
MercadoLibre's `/prices/standard/quantity` endpoint (PR 3). Max 5 tiers per
`publicacion_ml_id` is enforced at the SERVICE layer (422), not here.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


# `estado` drives whether a tier is priced and pushed to MercadoLibre, so a
# free-text column would let a typo sit forever in a state no branch handles,
# on a money path. The set is enforced by `ck_ml_pxq_tier_estado_valido`, and
# `test_declared_estado_constants_match_the_check_constraint` fails the moment
# either side drifts.
ESTADO_INCOMPLETO = "incompleto"
ESTADO_LISTO = "listo"
ESTADO_SINCRONIZADO = "sincronizado"
ESTADO_DESCONOCIDO = "desconocido"

ESTADOS_VALIDOS = (ESTADO_INCOMPLETO, ESTADO_LISTO, ESTADO_SINCRONIZADO, ESTADO_DESCONOCIDO)


class MlPxqTier(Base):
    __tablename__ = "ml_pxq_tier"

    id = Column(Integer, primary_key=True, index=True)

    publicacion_ml_id = Column(Integer, ForeignKey("publicaciones_ml.id"), nullable=False, index=True)
    item_id = Column(String(32), index=True, nullable=False)

    cantidad_minima = Column(Integer, nullable=False)
    precio_unitario = Column(Numeric(14, 2), nullable=False)
    costo_envio_total = Column(Numeric(14, 2), nullable=True)
    ml_price_id = Column(String(64), nullable=True)

    # Snapshot of what MercadoLibre confirmed at the last successful sync — the
    # shared base that makes the write a three-way merge instead of a guess.
    # Comparing only local-vs-live cannot tell who moved a value, so an edit on
    # either side looked identical and the local one silently won. NULL means
    # never synced, so there is nothing to have diverged from.
    cantidad_sincronizada = Column(Integer, nullable=True)
    precio_sincronizado = Column(Numeric(14, 2), nullable=True)

    # Both defaults on purpose: `default` covers ORM inserts, `server_default`
    # keeps the model in step with the migration so `alembic revision
    # --autogenerate` does not emit a spurious alter_column that nobody can
    # tell apart from a real one.
    estado = Column(String(16), nullable=False, default=ESTADO_INCOMPLETO, server_default=ESTADO_INCOMPLETO)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    publicacion = relationship("PublicacionML")
    usuario = relationship("Usuario")

    __table_args__ = (
        CheckConstraint("cantidad_minima > 1", name="ck_ml_pxq_tier_cantidad_minima_gt_1"),
        CheckConstraint(
            "estado IN ('incompleto', 'listo', 'sincronizado', 'desconocido')",
            name="ck_ml_pxq_tier_estado_valido",
        ),
        UniqueConstraint("publicacion_ml_id", "cantidad_minima", name="uq_ml_pxq_tier_publicacion_cantidad_minima"),
    )

    def __repr__(self) -> str:
        return f"<MlPxqTier(publicacion_ml_id={self.publicacion_ml_id}, cantidad_minima={self.cantidad_minima})>"
