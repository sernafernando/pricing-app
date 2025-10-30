from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.db.base_class import Base

class TipoAccion(str, enum.Enum):
    MODIFICAR_PRECIO_CLASICA = "modificar_precio_clasica"
    MODIFICAR_PRECIO_WEB = "modificar_precio_web"
    ACTIVAR_REBATE = "activar_rebate"
    DESACTIVAR_REBATE = "desactivar_rebate"
    MODIFICAR_PORCENTAJE_REBATE = "modificar_porcentaje_rebate"
    MARCAR_OUT_OF_CARDS = "marcar_out_of_cards"
    DESMARCAR_OUT_OF_CARDS = "desmarcar_out_of_cards"
    ACTIVAR_WEB_TRANSFERENCIA = "activar_web_transferencia"
    DESACTIVAR_WEB_TRANSFERENCIA = "desactivar_web_transferencia"
    MODIFICACION_MASIVA = "modificacion_masiva"

class Auditoria(Base):
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, index=True)  # Puede ser None si es masivo
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo_accion = Column(SQLEnum(TipoAccion), nullable=False, index=True)
    valores_anteriores = Column(JSON)  # Valores antes del cambio
    valores_nuevos = Column(JSON)  # Valores después del cambio
    es_masivo = Column(Integer, default=False)  # Si afectó a múltiples productos
    productos_afectados = Column(Integer)  # Cantidad de productos si es masivo
    comentario = Column(String(500))
    fecha = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relación
    usuario = relationship("Usuario", back_populates="auditorias")
