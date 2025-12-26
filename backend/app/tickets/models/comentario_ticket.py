from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ComentarioTicket(Base):
    """
    Comentarios en tickets para comunicación entre usuarios.
    
    Permite:
    - Discusión sobre el ticket
    - Solicitar aclaraciones
    - Proveer contexto adicional
    - Documentar decisiones
    
    Los comentarios pueden ser internos (solo visible para el equipo)
    o públicos (visible para el creador del ticket también).
    """
    __tablename__ = "tickets_comentarios"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id'), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=False)
    
    contenido = Column(Text, nullable=False)
    es_interno = Column(Boolean, default=False)  # Si es True, solo visible para usuarios con permisos
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    ticket = relationship("Ticket", back_populates="comentarios")
    usuario = relationship("Usuario")

    def __repr__(self):
        return f"<ComentarioTicket Ticket#{self.ticket_id} by User#{self.usuario_id}>"
