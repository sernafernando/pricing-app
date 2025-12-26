from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class HistorialTicket(Base):
    """
    Registra todos los cambios importantes en un ticket.
    
    Mantiene un log completo de:
    - Cambios de estado
    - Modificaciones de campos
    - Asignaciones/reasignaciones
    - Cualquier acción relevante
    
    Permite auditar completamente la vida del ticket y responder:
    - ¿Quién cambió qué y cuándo?
    - ¿Cuánto tiempo estuvo en cada estado?
    - ¿Por qué se tomó cada decisión?
    """
    __tablename__ = "tickets_historial"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id'), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=True)  # Null si fue automático
    
    accion = Column(String(100), nullable=False)  # created, estado_changed, asignado, comentado, metadata_updated
    descripcion = Column(Text)  # Descripción human-readable de la acción
    
    estado_anterior_id = Column(Integer, ForeignKey('tickets_estados.id'), nullable=True)
    estado_nuevo_id = Column(Integer, ForeignKey('tickets_estados.id'), nullable=True)
    
    # Cambios en formato estructurado
    cambios = Column(JSONB, default=dict)
    """
    {
        "campo": "prioridad",
        "valor_anterior": "media",
        "valor_nuevo": "alta"
    }
    
    o para metadata:
    {
        "campo": "metadata.precio_solicitado",
        "valor_anterior": 1500.00,
        "valor_nuevo": 1350.00
    }
    """
    
    fecha = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relaciones
    ticket = relationship("Ticket", back_populates="historial")
    usuario = relationship("Usuario")
    estado_anterior = relationship("EstadoTicket", foreign_keys=[estado_anterior_id])
    estado_nuevo = relationship("EstadoTicket", foreign_keys=[estado_nuevo_id])

    def __repr__(self):
        return f"<HistorialTicket Ticket#{self.ticket_id}: {self.accion}>"
