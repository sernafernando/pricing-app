"""
Modelo ProveedorDireccion — direcciones/depósitos de un proveedor.

Cada proveedor puede tener múltiples direcciones (depósito principal,
depósito secundario, oficina comercial, etc.). Las direcciones de
entrega RMA se migran acá. Soporte soft-delete (activo=False).
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ProveedorDireccion(Base):
    __tablename__ = "proveedor_direcciones"

    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Tipo/etiqueta ─────────────────────────────────────────────
    # Ej: "Depósito principal", "Depósito Zona Sur", "Oficina comercial"
    etiqueta = Column(String(100), nullable=False, default="Depósito")

    # ── Dirección ─────────────────────────────────────────────────
    direccion = Column(String(500), nullable=False)
    cp = Column(String(20), nullable=True)
    ciudad = Column(String(255), nullable=True)
    provincia = Column(String(255), nullable=True)

    # ── Datos de recepción ────────────────────────────────────────
    horario_recepcion = Column(String(255), nullable=True)
    contacto_nombre = Column(String(255), nullable=True)
    contacto_telefono = Column(String(100), nullable=True)
    notas = Column(Text, nullable=True)

    # ── Origen (para saber de dónde vino) ─────────────────────────
    # "rma" = migrada desde rma_proveedores, "manual" = cargada a mano
    origen = Column(String(20), nullable=False, default="manual")

    # ── Soft delete ───────────────────────────────────────────────
    activo = Column(Boolean, default=True, nullable=False)

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
    proveedor = relationship("Proveedor", back_populates="direcciones")

    def __repr__(self) -> str:
        return f"<ProveedorDireccion(id={self.id}, etiqueta='{self.etiqueta}', activo={self.activo})>"
