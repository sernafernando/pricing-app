"""
Modelo RmaProveedor — datos extendidos de proveedores para el módulo RMA.

Se alimenta del sync del ERP (supp_id, comp_id, nombre, cuit) y agrega
campos propios (dirección, contacto, configuración RMA) que no se pisan
cuando corre la sincronización.
"""

from datetime import datetime, UTC

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)

from app.core.database import Base


class RmaProveedor(Base):
    __tablename__ = "rma_proveedores"

    id = Column(Integer, primary_key=True, index=True)

    # Vínculo con tb_supplier (ERP) — sin FK formal por PK compuesta
    supp_id = Column(BigInteger, index=True)
    comp_id = Column(Integer, default=1)

    # Datos base (se sincronizan desde ERP, se pueden editar a mano)
    nombre = Column(String(255), nullable=False)
    cuit = Column(String(20), nullable=True)

    # Datos extendidos (propios, nunca pisados por sync)
    direccion = Column(String(500), nullable=True)
    cp = Column(String(20), nullable=True)
    ciudad = Column(String(255), nullable=True)
    provincia = Column(String(255), nullable=True)
    telefono = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    representante = Column(String(255), nullable=True)  # contacto servicio técnico
    horario = Column(String(255), nullable=True)  # ej: "Lun-Vie 9-17"
    notas = Column(Text, nullable=True)

    # Configuración RMA
    unidades_minimas_rma = Column(Integer, nullable=True)  # para alerta de envío

    # Estado
    activo = Column(Boolean, default=True, nullable=False)

    # Auditoría
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

    def __repr__(self) -> str:
        return f"<RmaProveedor(id={self.id}, supp_id={self.supp_id}, nombre='{self.nombre}')>"
