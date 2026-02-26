from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Transporte(Base):
    """
    Transportes interprovinciales disponibles para asignar a envíos flex.

    A diferencia de una Logística (que lleva el paquete del depósito al transporte),
    un Transporte es un intermediario que recibe el paquete y lo lleva al cliente
    final en otra provincia. Ej: Cruz del Sur, Vía Cargo, Chevallier Cargas.

    El flujo completo es:
        Depósito → [Logística] → [Transporte] → [Cliente]

    En la grilla de Envíos Flex, cuando un envío tiene transporte asignado,
    la columna "Dirección" muestra la dirección del transporte (donde la
    logística debe entregar). En la etiqueta impresa se imprime la dirección
    del cliente (destino final del transporte).
    """

    __tablename__ = "transportes"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), unique=True, nullable=False)
    cuit = Column(String(13), nullable=True)  # Formato: XX-XXXXXXXX-X
    direccion = Column(String(500), nullable=True)  # Dirección de la terminal/depósito
    cp = Column(String(10), nullable=True)  # Código postal de la terminal
    localidad = Column(String(200), nullable=True)  # Ciudad/localidad de la terminal
    telefono = Column(String(50), nullable=True)
    horario = Column(String(200), nullable=True)  # Ej: "Lun-Vie 8:00-17:00"
    activa = Column(Boolean, default=True, nullable=False)
    color = Column(String(7), nullable=True)  # Hex color para badge, ej: "#3b82f6"

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Transporte(id={self.id}, nombre='{self.nombre}')>"
