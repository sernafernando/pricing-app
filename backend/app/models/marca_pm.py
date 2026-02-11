from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class MarcaPM(Base):
    __tablename__ = "marcas_pm"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String(100), index=True, nullable=False)
    categoria = Column(String(100), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    fecha_asignacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_modificacion = Column(DateTime(timezone=True), onupdate=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="marcas_asignadas")

    __table_args__ = (
        UniqueConstraint("marca", "categoria", name="marcas_pm_marca_categoria_key"),
        Index("idx_marcas_pm_categoria", "categoria"),
    )
