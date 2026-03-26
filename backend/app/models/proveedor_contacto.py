"""
Modelo ProveedorContacto — contactos de un proveedor.

Cada proveedor puede tener múltiples contactos con distintos roles:
ventas, pagos, facturación, técnico, logística, etc.
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


class ProveedorContacto(Base):
    __tablename__ = "proveedor_contactos"

    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Datos del contacto ────────────────────────────────────────
    nombre = Column(String(255), nullable=False)
    rol = Column(String(100), nullable=True)  # "Ventas", "Pagos", "Facturación", "Técnico", etc.
    telefono = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    cargo = Column(String(255), nullable=True)  # "Gerente comercial", "Analista de pagos"
    notas = Column(Text, nullable=True)

    # ── Estado ────────────────────────────────────────────────────
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
    proveedor = relationship("Proveedor", back_populates="contactos")

    def __repr__(self) -> str:
        return f"<ProveedorContacto(id={self.id}, nombre='{self.nombre}', rol='{self.rol}')>"
