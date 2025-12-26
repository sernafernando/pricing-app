from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class PrioridadTicket(str, enum.Enum):
    """Niveles de prioridad para tickets"""
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class Ticket(Base):
    """
    Modelo principal de ticket.
    
    Combina campos estructurados (core) con campos dinámicos (metadata JSONB)
    para máxima flexibilidad sin sacrificar performance en queries comunes.
    
    Los campos core son:
    - Información básica: título, descripción, prioridad
    - Referencias: sector, tipo, estado, usuario creador
    - Timestamps: created_at, updated_at
    
    Los campos custom por tipo de ticket van en metadata (JSONB).
    """
    __tablename__ = "tickets"

    # Campos core (columnas estructuradas para performance)
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    prioridad = Column(SQLEnum(PrioridadTicket), default=PrioridadTicket.MEDIA, nullable=False)

    # Referencias
    sector_id = Column(Integer, ForeignKey('tickets_sectores.id'), nullable=False, index=True)
    tipo_ticket_id = Column(Integer, ForeignKey('tickets_tipos.id'), nullable=False)
    estado_id = Column(Integer, ForeignKey('tickets_estados.id'), nullable=False, index=True)
    creador_id = Column(Integer, ForeignKey('usuarios.id'), nullable=False)

    # Campos dinámicos (JSONB para flexibilidad)
    metadata = Column(JSONB, nullable=False, default=dict)
    """
    Campos específicos según el tipo de ticket:
    
    Para Cambio de Precio:
    {
        "item_id": 12345,
        "precio_actual": 1500.00,
        "precio_solicitado": 1350.00,
        "motivo": "Competencia bajó precio",
        "urgencia": "alta"
    }
    
    Para Bug:
    {
        "severidad": "critica",
        "pasos_reproducir": "...",
        "navegador": "Chrome 120",
        "screenshot_url": "...",
        "url_afectada": "..."
    }
    """

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    sector = relationship("Sector", back_populates="tickets")
    tipo_ticket = relationship("TipoTicket", back_populates="tickets")
    estado = relationship("EstadoTicket", back_populates="tickets")
    creador = relationship("Usuario", foreign_keys=[creador_id])
    
    asignaciones = relationship("AsignacionTicket", back_populates="ticket", order_by="AsignacionTicket.fecha_asignacion.desc()")
    historial = relationship("HistorialTicket", back_populates="ticket", order_by="HistorialTicket.fecha.desc()")
    comentarios = relationship("ComentarioTicket", back_populates="ticket", order_by="ComentarioTicket.created_at.asc()")

    @property
    def asignacion_actual(self):
        """Retorna la asignación activa (sin fecha de finalización)"""
        for asignacion in self.asignaciones:
            if asignacion.fecha_finalizacion is None:
                return asignacion
        return None

    @property
    def asignado_a(self):
        """Retorna el usuario actualmente asignado o None"""
        asignacion = self.asignacion_actual
        return asignacion.asignado_a if asignacion else None

    @property
    def esta_cerrado(self):
        """Verifica si el ticket está en un estado final"""
        return self.estado.es_final if self.estado else False

    def __repr__(self):
        return f"<Ticket #{self.id}: {self.titulo[:50]}>"
