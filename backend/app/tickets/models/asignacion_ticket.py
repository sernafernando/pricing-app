from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class TipoAsignacion(str, enum.Enum):
    """Tipo de asignación del ticket"""

    MANUAL = "manual"
    AUTOMATICO = "automatico"
    REASIGNACION = "reasignacion"
    ESCALAMIENTO = "escalamiento"


class AsignacionTicket(Base):
    """
    Registra las asignaciones de tickets a usuarios.

    Mantiene un historial completo de todas las asignaciones:
    - Quién fue asignado
    - Quién hizo la asignación
    - Cuándo fue asignado
    - Por qué (tipo de asignación y motivo opcional)
    - Cuándo finalizó la asignación

    Un ticket puede tener múltiples asignaciones a lo largo del tiempo,
    pero solo una activa (sin fecha_finalizacion).
    """

    __tablename__ = "tickets_asignaciones"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    asignado_a_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    asignado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # Null si fue automático

    tipo = Column(SQLEnum(TipoAsignacion), nullable=False)
    motivo = Column(String(500), nullable=True)  # Motivo de reasignación o escalamiento

    fecha_asignacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_finalizacion = Column(DateTime(timezone=True), nullable=True)  # Null = asignación activa

    # Relaciones
    ticket = relationship("Ticket", back_populates="asignaciones")
    asignado_a = relationship("Usuario", foreign_keys=[asignado_a_id])
    asignado_por = relationship("Usuario", foreign_keys=[asignado_por_id])

    @property
    def esta_activa(self):
        """Verifica si esta asignación está activa"""
        return self.fecha_finalizacion is None

    def __repr__(self):
        return f"<AsignacionTicket Ticket#{self.ticket_id} → Usuario#{self.asignado_a_id} ({self.tipo})>"
