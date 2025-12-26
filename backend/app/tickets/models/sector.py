from sqlalchemy import Column, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Sector(Base):
    """
    Representa un sector o área de la empresa que maneja tickets.
    
    Ejemplos:
    - Pricing: Maneja solicitudes de cambio de precio, activación de rebates
    - Soporte: Maneja bugs, feature requests, consultas técnicas
    - Ventas: Maneja consultas comerciales, cotizaciones
    
    Cada sector puede tener:
    - Su propio workflow de estados
    - Reglas de asignación específicas
    - Configuración de notificaciones
    - SLA específico
    """
    __tablename__ = "tickets_sectores"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)  # pricing, soporte, ventas
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    icono = Column(String(50))  # Para UI (ej: "chart-line", "bug", "shopping-cart")
    color = Column(String(20))  # Para UI (ej: "#3B82F6")
    activo = Column(Boolean, default=True)

    # Configuración flexible en JSONB
    configuracion = Column(JSONB, nullable=False, default=dict)
    """
    Estructura de configuracion:
    {
        "asignacion": {
            "tipo": "round_robin" | "basado_en_carga" | "basado_en_skills" | "manual",
            "auto_assign": bool,
            "solo_con_permiso": str,  # Código de permiso requerido
            "skill_field": str,  # Campo en metadata para skill-based (ej: "marca_id")
            "fallback": str  # Estrategia fallback si skill-based falla
        },
        "notificaciones": {
            "on_create": ["email", "in_app", "slack_webhook"],
            "on_assign": ["in_app"],
            "on_estado_changed": ["email", "in_app"],
            "on_comentario": ["in_app"],
            "on_close": ["email"],
            "webhook_url": str,  # Para integraciones externas
            "destinatarios_default": [user_ids]
        },
        "sla": {
            "respuesta_horas": int,
            "resolucion_horas": int,
            "escalamiento_auto_horas": int
        },
        "campos_requeridos": [str],  # Campos que deben estar en metadata
        "workflow_default_id": int
    }
    """

    # Relaciones
    workflows = relationship("Workflow", back_populates="sector", cascade="all, delete-orphan")
    tipos_ticket = relationship("TipoTicket", back_populates="sector", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="sector")

    def __repr__(self):
        return f"<Sector {self.codigo}: {self.nombre}>"
