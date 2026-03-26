"""
Modelo ImpuestoEmpresa — impuestos, retenciones y percepciones que maneja la empresa.

Tabla de configuración interna. Define los tipos de impuesto con sus
alícuotas para usar en facturación, pagos a proveedores, retenciones, etc.
No se consulta a AFIP — es un ABM propio de la empresa.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)

from app.core.database import Base


class ImpuestoEmpresa(Base):
    __tablename__ = "impuestos_empresa"

    id = Column(Integer, primary_key=True, index=True)

    # ── Identificación ────────────────────────────────────────────
    nombre = Column(String(255), nullable=False)  # "IVA 21%", "Ret. Ganancias", etc.
    tipo = Column(String(50), nullable=False)  # iva, retencion, percepcion, otro
    codigo_afip = Column(Integer, nullable=True)  # ID de AFIP (30=IVA, 217=Ret.Gan, etc.)

    # ── Alícuota ──────────────────────────────────────────────────
    alicuota = Column(Numeric(8, 4), nullable=False)  # Porcentaje: 21.0000, 10.5000, 3.0000

    # ── Aplicación ────────────────────────────────────────────────
    aplica_a = Column(String(20), nullable=False, default="ambos")  # compras, ventas, ambos

    # ── Notas ─────────────────────────────────────────────────────
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

    def __repr__(self) -> str:
        return f"<ImpuestoEmpresa(id={self.id}, nombre='{self.nombre}', alicuota={self.alicuota})>"
