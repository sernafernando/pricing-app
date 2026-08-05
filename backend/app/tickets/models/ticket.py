from sqlalchemy import CheckConstraint, Column, Index, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
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
    # ponytail: prioridad kept for backward compat, deprecated in the UI in
    # favor of severidad/urgencia below — do NOT derive it from them, and do
    # NOT derive severidad/urgencia from it. Deriving either direction would
    # silently overwrite values a human set by hand.
    prioridad = Column(
        SQLEnum(PrioridadTicket, values_callable=lambda e: [x.value for x in e]),
        default=PrioridadTicket.MEDIA,
        nullable=False,
    )

    # AI triage fields (tickets-ai-triage). All nullable: NULL means
    # "unclassified" — nothing writes these until a proposal is confirmed
    # (see tickets_propuestas_ia, a later slice). Never a Postgres ENUM type:
    # you cannot drop an enum value, so a migration downgrade() would be a
    # lie — see `prioridad` above, which already made that mistake.
    severidad = Column(String(12), nullable=True)
    urgencia = Column(String(12), nullable=True)
    severidad_origen = Column(String(14), nullable=True)
    urgencia_origen = Column(String(14), nullable=True)
    texto_original = Column(Text, nullable=True)

    # Referencias
    sector_id = Column(Integer, ForeignKey("tickets_sectores.id"), nullable=False, index=True)
    tipo_ticket_id = Column(Integer, ForeignKey("tickets_tipos.id"), nullable=False)
    estado_id = Column(Integer, ForeignKey("tickets_estados.id"), nullable=False, index=True)
    creador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)

    # Campos dinámicos (JSONB para flexibilidad)
    # NOTE: The Python attribute is 'campos_metadata' because 'metadata' is reserved
    # by SQLAlchemy's Declarative API. The DB column name stays 'metadata'.
    campos_metadata = Column("metadata", JSONB, nullable=False, default=dict)
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

    __table_args__ = (
        CheckConstraint(
            "severidad IN ('trivial','menor','mayor','critica')",
            name="ck_tickets_severidad",
        ),
        CheckConstraint(
            "urgencia IN ('baja','normal','alta','inmediata')",
            name="ck_tickets_urgencia",
        ),
        CheckConstraint(
            "severidad_origen IN ('humano','ia_confirmada','ia_auto')",
            name="ck_tickets_severidad_origen",
        ),
        CheckConstraint(
            "urgencia_origen IN ('humano','ia_confirmada','ia_auto')",
            name="ck_tickets_urgencia_origen",
        ),
        Index("ix_tickets_severidad", "severidad"),
        Index("ix_tickets_urgencia", "urgencia"),
        Index("ix_tickets_estado_urgencia_created", "estado_id", "urgencia", "created_at"),
    )

    # Relaciones
    sector = relationship("Sector", back_populates="tickets")
    tipo_ticket = relationship("TipoTicket", back_populates="tickets")
    estado = relationship("EstadoTicket", back_populates="tickets")
    creador = relationship("Usuario", foreign_keys=[creador_id])

    asignaciones = relationship(
        "AsignacionTicket", back_populates="ticket", order_by="AsignacionTicket.fecha_asignacion.desc()"
    )
    historial = relationship("HistorialTicket", back_populates="ticket", order_by="HistorialTicket.fecha.desc()")
    comentarios = relationship(
        "ComentarioTicket", back_populates="ticket", order_by="ComentarioTicket.created_at.asc()"
    )
    adjuntos = relationship(
        "AdjuntoTicket",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="AdjuntoTicket.created_at.asc()",
    )

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
