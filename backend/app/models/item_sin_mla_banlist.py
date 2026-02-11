from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class ItemSinMLABanlist(Base):
    """
    Modelo para items que no queremos que aparezcan en el listado de productos sin MLA
    Almacena el item_id para excluirlo del reporte
    """
    __tablename__ = "items_sin_mla_banlist"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, unique=True, index=True, nullable=False)
    motivo = Column(Text, nullable=True)  # Razón por la cual se agregó a la banlist

    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="items_sin_mla_baneados")

    def __repr__(self):
        return f"<ItemSinMLABanlist(item_id={self.item_id})>"
