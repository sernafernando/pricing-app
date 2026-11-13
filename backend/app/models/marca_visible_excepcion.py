"""Brands that stay visible in every brand option list even with no stock (admin exception list).

A brand with no product in stock is hidden from every brand filter and selector
(`app.services.marcas_visibles`); a brand listed here is offered anyway. Managed
from the Admin panel ("Marcas sin stock visibles").
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class MarcaVisibleExcepcion(Base):
    """One brand the admin keeps visible without stock: who added it and when."""

    __tablename__ = "marcas_visibles_excepciones"
    __table_args__ = (UniqueConstraint("marca", name="uq_marcas_visibles_excepciones_marca"),)

    id = Column(Integer, primary_key=True)
    marca = Column(String(100), nullable=False)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    creado_por = relationship("Usuario", lazy="joined")

    def __repr__(self) -> str:
        return f"<MarcaVisibleExcepcion(marca={self.marca!r})>"
