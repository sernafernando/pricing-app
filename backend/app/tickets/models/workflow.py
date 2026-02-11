from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Workflow(Base):
    """
    Define un flujo de trabajo (workflow) con sus estados y transiciones.

    Cada sector puede tener múltiples workflows, pero uno es el default.
    Permite modelar procesos diferentes dentro del mismo sector.

    Ejemplo Pricing:
    - Workflow "Cambio de Precio": Solicitado → Revisión → Aprobado → Aplicado
    - Workflow "Rebate": Solicitado → Aprobado → Activo
    """

    __tablename__ = "tickets_workflows"

    id = Column(Integer, primary_key=True, index=True)
    sector_id = Column(Integer, ForeignKey("tickets_sectores.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    es_default = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)

    # Relaciones
    sector = relationship("Sector", back_populates="workflows")
    estados = relationship(
        "EstadoTicket", back_populates="workflow", cascade="all, delete-orphan", order_by="EstadoTicket.orden"
    )
    transiciones = relationship("TransicionEstado", back_populates="workflow", cascade="all, delete-orphan")
    tipos_ticket = relationship("TipoTicket", back_populates="workflow")

    def __repr__(self):
        return f"<Workflow {self.nombre} (Sector: {self.sector.codigo if self.sector else 'N/A'})>"


class EstadoTicket(Base):
    """
    Representa un estado dentro de un workflow.

    Ejemplos:
    - Abierto, En Revisión, Aprobado, Rechazado, Aplicado
    - Reportado, En Investigación, En Desarrollo, Testing, Resuelto
    """

    __tablename__ = "tickets_estados"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("tickets_workflows.id"), nullable=False)
    codigo = Column(String(50), nullable=False)  # abierto, en_revision, aprobado
    nombre = Column(String(100), nullable=False)  # "Abierto", "En Revisión", "Aprobado"
    descripcion = Column(Text)
    orden = Column(Integer, nullable=False)  # Para ordenar en UI
    color = Column(String(20))  # Para UI (ej: "#10B981" para aprobado)
    es_inicial = Column(Boolean, default=False)  # Estado cuando se crea el ticket
    es_final = Column(Boolean, default=False)  # Estado terminal (cerrado, resuelto, rechazado)

    # Acciones automáticas al entrar en este estado
    acciones_on_enter = Column(JSONB, default=list)
    """
    [
        {"tipo": "notificar", "destinatarios": ["asignado", "creador"]},
        {"tipo": "webhook", "url": "https://..."},
        {"tipo": "ejecutar_callback", "funcion": "apply_price_change"}
    ]
    """

    # Relaciones
    workflow = relationship("Workflow", back_populates="estados")
    tickets = relationship("Ticket", back_populates="estado")
    transiciones_origen = relationship(
        "TransicionEstado", foreign_keys="TransicionEstado.estado_origen_id", back_populates="estado_origen"
    )
    transiciones_destino = relationship(
        "TransicionEstado", foreign_keys="TransicionEstado.estado_destino_id", back_populates="estado_destino"
    )

    def __repr__(self):
        return f"<EstadoTicket {self.codigo}: {self.nombre}>"


class TransicionEstado(Base):
    """
    Define una transición permitida entre dos estados.

    Controla:
    - Quién puede hacer la transición (permisos)
    - Qué validaciones debe pasar
    - Qué acciones ejecutar al hacer la transición

    Ejemplo:
    - De "En Revisión" a "Aprobado" requiere permiso "tickets.pricing.aprobar"
    - De "Aprobado" a "Aplicado" ejecuta callback para cambiar el precio
    """

    __tablename__ = "tickets_transiciones"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("tickets_workflows.id"), nullable=False)
    estado_origen_id = Column(Integer, ForeignKey("tickets_estados.id"), nullable=False)
    estado_destino_id = Column(Integer, ForeignKey("tickets_estados.id"), nullable=False)

    nombre = Column(String(100))  # "Aprobar", "Rechazar", "Aplicar Cambio"
    descripcion = Column(Text)

    # Control de acceso
    requiere_permiso = Column(String(100))  # Código de permiso (ej: "tickets.pricing.aprobar")
    solo_asignado = Column(Boolean, default=False)  # Solo el usuario asignado puede hacer esta transición
    solo_creador = Column(Boolean, default=False)  # Solo el creador puede hacer esta transición

    # Validaciones que deben pasar antes de permitir la transición
    validaciones = Column(JSONB, default=list)
    """
    [
        {
            "tipo": "campo_requerido",
            "campo": "resolucion",
            "mensaje": "Debe completar la resolución antes de cerrar"
        },
        {
            "tipo": "callback",
            "funcion": "validate_price_in_range",
            "mensaje": "El precio está fuera del rango permitido"
        }
    ]
    """

    # Acciones a ejecutar al realizar la transición
    acciones = Column(JSONB, default=list)
    """
    [
        {"tipo": "notificar", "destinatarios": ["creador"]},
        {"tipo": "ejecutar_callback", "funcion": "apply_price_change"},
        {"tipo": "crear_auditoria", "categoria": "pricing"}
    ]
    """

    # Relaciones
    workflow = relationship("Workflow", back_populates="transiciones")
    estado_origen = relationship("EstadoTicket", foreign_keys=[estado_origen_id], back_populates="transiciones_origen")
    estado_destino = relationship(
        "EstadoTicket", foreign_keys=[estado_destino_id], back_populates="transiciones_destino"
    )

    def __repr__(self):
        origen = self.estado_origen.nombre if self.estado_origen else "?"
        destino = self.estado_destino.nombre if self.estado_destino else "?"
        return f"<TransicionEstado {origen} → {destino}>"
