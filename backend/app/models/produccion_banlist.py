from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ProduccionBanlist(Base):
    """
    Modelo para items que no queremos que aparezcan en Producción - Preparación.
    Permite excluir productos que no tienen sentido en esa vista.
    """

    __tablename__ = "produccion_banlist"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, unique=True, index=True, nullable=False)
    motivo = Column(Text, nullable=True)  # Razón por la cual se agregó al banlist

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="items_produccion_baneados")

    def __repr__(self):
        return f"<ProduccionBanlist(item_id={self.item_id})>"


class ProduccionPrearmado(Base):
    """
    Modelo para marcar productos que están en proceso de pre-armado.
    Incluye la cantidad de unidades que se están pre-armando.
    Se auto-limpia cuando el producto desaparece del ERP.
    """

    __tablename__ = "produccion_prearmado"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, unique=True, index=True, nullable=False)
    cantidad = Column(Integer, nullable=False, default=1)  # Cantidad de unidades pre-armando
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="items_prearmados")

    def __repr__(self):
        return f"<ProduccionPrearmado(item_id={self.item_id}, cantidad={self.cantidad})>"
