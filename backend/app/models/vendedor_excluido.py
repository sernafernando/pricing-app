"""
Modelo para vendedores excluidos de los reportes de ventas fuera de ML
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class VendedorExcluido(Base):
    """Vendedores que se excluyen de los reportes de ventas por fuera de ML"""
    __tablename__ = "vendedores_excluidos"

    id = Column(Integer, primary_key=True, index=True)
    sm_id = Column(Integer, nullable=False, unique=True, index=True)
    sm_name = Column(String(255))  # Nombre del vendedor (para referencia)
    motivo = Column(String(500))  # Motivo de la exclusión

    # Auditoría
    creado_por = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<VendedorExcluido(sm_id={self.sm_id}, sm_name='{self.sm_name}')>"
