from sqlalchemy import Column, Integer, ForeignKey, DateTime, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ComparacionListasBanlist(Base):
    """
    Modelo para publicaciones MLA que no queremos que aparezcan en la
    comparación de listas (errores ya revisados / falsos positivos).
    Se clave en mla_id porque la comparación opera a nivel publicación.
    """

    __tablename__ = "comparacion_listas_banlist"

    id = Column(Integer, primary_key=True, index=True)
    mla_id = Column(String(50), unique=True, index=True, nullable=False)
    motivo = Column(Text, nullable=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="comparacion_listas_baneadas")

    def __repr__(self):
        return f"<ComparacionListasBanlist(mla_id={self.mla_id})>"
