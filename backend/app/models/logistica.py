from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Logistica(Base):
    """
    Logísticas disponibles para asignar a envíos flex.
    Ej: "Andreani", "OCA", "Flex propio", etc.
    Se gestionan desde el panel de PedidosPreparacion > Envíos Flex.
    """

    __tablename__ = "logisticas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    activa = Column(Boolean, default=True, nullable=False)
    color = Column(String(7), nullable=True)  # Hex color para badge, ej: "#3b82f6"
    pistoleado_asigna = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="Si True, al pistolear asigna la logística en vez de verificar coincidencia",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Logistica(id={self.id}, nombre='{self.nombre}')>"
