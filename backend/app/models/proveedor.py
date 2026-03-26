"""
Modelo Proveedor — tabla centralizada de proveedores.

Cada módulo (RMA, Administración, Compras) consume la misma tabla base
y tiene sus propias tablas de extensión para datos específicos del dominio.

Origen de datos:
  - ERP (GBP): sincronizados via sync_suppliers → tb_supplier → proveedores
  - Manual: creados desde la UI de Administración
"""

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class OrigenProveedor(str, enum.Enum):
    ERP = "erp"
    MANUAL = "manual"


class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)

    # ── Vínculo con ERP (tb_supplier) ─────────────────────────────
    # Sin FK formal porque tb_supplier tiene PK compuesta (comp_id, supp_id)
    supp_id = Column(BigInteger, index=True, nullable=True)
    comp_id = Column(Integer, default=1, nullable=True)

    # ── Datos base ────────────────────────────────────────────────
    nombre = Column(String(255), nullable=False, index=True)
    cuit = Column(String(20), nullable=True, index=True)
    origen = Column(
        String(10),
        nullable=False,
        default=OrigenProveedor.ERP,
    )

    # ── Datos de contacto (compartidos entre módulos) ─────────────
    direccion = Column(String(500), nullable=True)
    cp = Column(String(20), nullable=True)
    ciudad = Column(String(255), nullable=True)
    provincia = Column(String(255), nullable=True)
    telefono = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    representante = Column(String(255), nullable=True)
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

    # ── Relaciones ────────────────────────────────────────────────
    datos_fiscales = relationship(
        "ProveedorDatosFiscales",
        back_populates="proveedor",
        uselist=False,
        cascade="all, delete-orphan",
    )
    datos_rma = relationship(
        "RmaProveedor",
        back_populates="proveedor",
        uselist=False,
    )
    direcciones = relationship(
        "ProveedorDireccion",
        back_populates="proveedor",
        cascade="all, delete-orphan",
        order_by="ProveedorDireccion.etiqueta",
    )
    bancos = relationship(
        "ProveedorBanco",
        back_populates="proveedor",
        cascade="all, delete-orphan",
        order_by="ProveedorBanco.banco",
    )
    contactos = relationship(
        "ProveedorContacto",
        back_populates="proveedor",
        cascade="all, delete-orphan",
        order_by="ProveedorContacto.nombre",
    )

    def __repr__(self) -> str:
        return f"<Proveedor(id={self.id}, nombre='{self.nombre}', cuit='{self.cuit}')>"
