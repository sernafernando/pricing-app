from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Colecta(Base):
    """
    Colecta — agrupación lógica de etiquetas que salen juntas en un mismo retiro.

    Una colecta es identificada por (fecha, numero) — por ejemplo (2026-05-07, 1)
    es la primera colecta del 7 de mayo. Pueden coexistir múltiples colectas el
    mismo día (ej. una de mañana y otra de tarde).

    Estados:
      - 'pendiente'  → la colecta está siendo armada/escaneada
      - 'despachada' → ya se fue, queda como histórico
    """

    __tablename__ = "colectas"

    ESTADO_PENDIENTE = "pendiente"
    ESTADO_DESPACHADA = "despachada"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False)
    numero = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_PENDIENTE)
    despachada_at = Column(DateTime(timezone=True), nullable=True)
    observaciones = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    etiquetas = relationship(
        "EtiquetaColecta",
        back_populates="colecta",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("fecha", "numero", name="uq_colecta_fecha_numero"),
        Index("idx_colectas_fecha", "fecha"),
        Index("idx_colectas_estado", "estado"),
    )
