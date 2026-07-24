from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class MarcaSubPM(Base):
    """Sub-PM delegation grant: a (marca, categoria) pair may have multiple
    sub-PM users in addition to its single titular in `marcas_pm`. Unlike
    `marcas_pm`, the (marca, categoria) pair is NOT unique here — the same
    pair can have several sub-PM grants, one per delegated `usuario_id`.
    """

    __tablename__ = "marca_sub_pm"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String(100), nullable=False)
    categoria = Column(String(100), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    creador = relationship("Usuario", foreign_keys=[creado_por])

    __table_args__ = (
        UniqueConstraint("marca", "categoria", "usuario_id", name="marca_sub_pm_marca_categoria_usuario_key"),
        Index("ix_marca_sub_pm_usuario_id", "usuario_id"),
        Index("ix_marca_sub_pm_marca_categoria", "marca", "categoria"),
    )
