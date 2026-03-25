"""
Modelo RmaProveedor — datos extendidos de proveedores para el módulo RMA.

Extensión del modelo central `Proveedor` con datos específicos de RMA:
dirección de entrega (puede diferir del domicilio fiscal), horario de
recepción, contacto de servicio técnico, y configuración de envíos RMA.

FK a `proveedores.id` — los datos base (nombre, CUIT, contacto general)
viven en la tabla central. RMA solo agrega lo propio del dominio.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class RmaProveedor(Base):
    __tablename__ = "rma_proveedores"

    id = Column(Integer, primary_key=True, index=True)

    # ── FK a tabla central de proveedores ─────────────────────────
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="CASCADE"),
        nullable=True,  # nullable durante migración, después NOT NULL
        unique=True,
        index=True,
    )

    # ── Campos legacy (se mantienen por compatibilidad) ───────────
    # TODO: migrar queries a usar proveedor.nombre/cuit vía join
    supp_id = Column(Integer, index=True, nullable=True)
    comp_id = Column(Integer, default=1, nullable=True)
    nombre = Column(String(255), nullable=False)
    cuit = Column(String(20), nullable=True)

    # ── Datos específicos RMA ─────────────────────────────────────
    # Dirección de ENTREGA para RMA (puede ser distinta al domicilio fiscal)
    direccion_entrega = Column(String(500), nullable=True)
    cp_entrega = Column(String(20), nullable=True)
    ciudad_entrega = Column(String(255), nullable=True)
    provincia_entrega = Column(String(255), nullable=True)
    representante_tecnico = Column(String(255), nullable=True)
    horario_recepcion = Column(String(255), nullable=True)  # ej: "Lun-Vie 9-17"
    notas_rma = Column(Text, nullable=True)
    unidades_minimas_rma = Column(Integer, nullable=True)

    # ── Campos legacy renombrados (alias para migración gradual) ──
    # Estos se mantienen con los nombres originales en la DB
    # para no romper queries existentes
    direccion = Column(String(500), nullable=True)
    cp = Column(String(20), nullable=True)
    ciudad = Column(String(255), nullable=True)
    provincia = Column(String(255), nullable=True)
    telefono = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    representante = Column(String(255), nullable=True)
    horario = Column(String(255), nullable=True)
    notas = Column(Text, nullable=True)
    activo = Column(Integer, default=1, nullable=True)

    # ── Auditoría ─────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=True,
    )

    # ── Relación ──────────────────────────────────────────────────
    proveedor = relationship("Proveedor", back_populates="datos_rma")

    def __repr__(self) -> str:
        return f"<RmaProveedor(id={self.id}, proveedor_id={self.proveedor_id}, nombre='{self.nombre}')>"
