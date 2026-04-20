"""
NumeracionContador — contador correlativo por (tipo, empresa, año).

Base de la numeración de pedidos de compra y órdenes de pago. La PK
compuesta permite secuencias independientes por tipo/empresa/año, y la
tabla se lockea con SELECT FOR UPDATE desde `numeracion_service` para
garantizar correlatividad sin gaps bajo concurrencia (v1 acepta gaps
legítimos por rollback — D21).

Zona horaria del año: Argentina (UTC-3), resuelta en el servicio (D18).
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.sql import func

from app.core.database import Base


class NumeracionContador(Base):
    """Contador correlativo para numeración de documentos del módulo compras."""

    __tablename__ = "numeracion_contadores"

    tipo = Column(String(24), nullable=False)
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    anio = Column(Integer, nullable=False)
    ultimo_numero = Column(Integer, nullable=False, default=0, server_default="0")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        PrimaryKeyConstraint("tipo", "empresa_id", "anio", name="pk_numeracion_contadores"),
        CheckConstraint("ultimo_numero >= 0", name="ck_numeracion_ultimo_numero_non_negative"),
        CheckConstraint("anio BETWEEN 2020 AND 2100", name="ck_numeracion_anio_range"),
    )

    def __repr__(self) -> str:
        return (
            f"<NumeracionContador(tipo='{self.tipo}', empresa_id={self.empresa_id}, "
            f"anio={self.anio}, ultimo_numero={self.ultimo_numero})>"
        )
