from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class TipoTicket(Base):
    """
    Define los diferentes tipos de tickets que puede haber en un sector.

    Ejemplos Sector Pricing:
    - Solicitud Cambio de Precio
    - Activación de Rebate
    - Consulta de Pricing

    Ejemplos Sector Soporte:
    - Bug
    - Feature Request
    - Consulta Técnica

    Cada tipo puede tener campos custom específicos definidos en schema_campos.
    """

    __tablename__ = "tickets_tipos"

    id = Column(Integer, primary_key=True, index=True)
    sector_id = Column(Integer, ForeignKey("tickets_sectores.id"), nullable=False)
    workflow_id = Column(
        Integer, ForeignKey("tickets_workflows.id"), nullable=True
    )  # Si null, usa workflow default del sector

    codigo = Column(String(50), nullable=False)  # cambio_precio, bug, consulta
    nombre = Column(String(100), nullable=False)  # "Solicitud Cambio de Precio"
    descripcion = Column(Text)
    icono = Column(String(50))  # Para UI
    color = Column(String(20))  # Para UI

    # Define el schema de campos custom que debe tener este tipo de ticket
    schema_campos = Column(JSONB, default=dict)
    """
    {
        "item_id": {
            "tipo": "integer",
            "requerido": true,
            "label": "ID del Producto",
            "descripcion": "ID del producto en el ERP"
        },
        "precio_actual": {
            "tipo": "decimal",
            "requerido": true,
            "label": "Precio Actual"
        },
        "precio_solicitado": {
            "tipo": "decimal",
            "requerido": true,
            "label": "Precio Solicitado"
        },
        "motivo": {
            "tipo": "text",
            "requerido": true,
            "label": "Motivo del Cambio",
            "max_length": 500
        },
        "urgencia": {
            "tipo": "select",
            "requerido": true,
            "label": "Urgencia",
            "opciones": ["baja", "media", "alta", "critica"]
        }
    }
    """

    # Relaciones
    sector = relationship("Sector", back_populates="tipos_ticket")
    workflow = relationship("Workflow", back_populates="tipos_ticket")
    tickets = relationship("Ticket", back_populates="tipo_ticket")

    def __repr__(self):
        return f"<TipoTicket {self.codigo}: {self.nombre}>"
