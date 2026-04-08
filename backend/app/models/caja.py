"""
Caja (Cash Register) — Administration Module.

Sistema de caja para seguimiento de ingresos y egresos.
Soporta múltiples cajas por empresa, categorización de movimientos,
documentos adjuntos con archivos, y sincronización desde Google Sheets.

Convención de saldo:
- saldo_actual se mantiene denormalizado en la cabecera (Caja)
- saldo_posterior en cada movimiento registra el saldo después de ese movimiento
- monto en movimientos es siempre positivo; el tipo (ingreso/egreso) determina dirección
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


# ──────────────────────────────────────────────
# Core tables (v1)
# ──────────────────────────────────────────────


class Caja(Base):
    """
    Cabecera de caja (efectivo o divisa).

    Una caja pertenece a una empresa y tiene una moneda fija.
    El saldo_actual se actualiza transaccionalmente con cada movimiento.
    """

    __tablename__ = "cajas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    moneda = Column(String(10), nullable=False, default="ARS")
    saldo_inicial = Column(Numeric(18, 2), nullable=False, default=0)
    saldo_actual = Column(Numeric(18, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empresa = relationship("Empresa")
    movimientos = relationship(
        "CajaMovimiento",
        back_populates="caja",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("nombre", "empresa_id", name="uq_caja_nombre_empresa"),)

    def __repr__(self) -> str:
        return f"<Caja(id={self.id}, nombre='{self.nombre}', moneda='{self.moneda}')>"


class CajaMovimiento(Base):
    """
    Movimiento individual de caja (ingreso o egreso).

    Los movimientos son inmutables: no se editan ni eliminan.
    Para corregir errores, se registra un movimiento compensatorio.
    """

    __tablename__ = "caja_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    caja_id = Column(
        Integer,
        ForeignKey("cajas.id", ondelete="CASCADE"),
        nullable=False,
    )
    fecha = Column(Date, nullable=False)
    detalle = Column(Text, nullable=False)
    tipo = Column(String(20), nullable=False)  # 'ingreso' o 'egreso'
    monto = Column(Numeric(18, 2), nullable=False)
    saldo_posterior = Column(Numeric(18, 2), nullable=False)
    categoria_id = Column(
        Integer,
        ForeignKey("caja_categorias.id", ondelete="SET NULL"),
        nullable=True,
    )
    origen = Column(String(20), nullable=False, default="manual")  # 'manual' o 'sync'
    registrado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    observaciones = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    caja = relationship("Caja", back_populates="movimientos")
    categoria = relationship("CajaCategoria")
    registrado_por = relationship("Usuario")
    documentos = relationship(
        "CajaDocumento",
        secondary="caja_documento_movimientos",
        back_populates="movimientos",
    )

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_caja_mov_monto_positivo"),
        Index("ix_caja_mov_caja_fecha", "caja_id", "fecha"),
        Index("ix_caja_mov_caja_tipo", "caja_id", "tipo"),
        Index("ix_caja_mov_categoria", "categoria_id"),
    )

    def __repr__(self) -> str:
        return f"<CajaMovimiento(id={self.id}, tipo='{self.tipo}', monto={self.monto})>"


class CajaCategoria(Base):
    """
    Categoría de movimiento (Gasto, Sueldos, Ingreso Venta, etc.).

    Las categorías son globales — compartidas por todas las cajas.
    tipo_aplicable controla en qué tipo de movimiento se puede usar.
    """

    __tablename__ = "caja_categorias"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)
    tipo_aplicable = Column(String(20), nullable=False, default="ambos")  # 'ingreso', 'egreso', 'ambos'
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<CajaCategoria(nombre='{self.nombre}', tipo='{self.tipo_aplicable}')>"


# ──────────────────────────────────────────────
# Document tables (v2)
# ──────────────────────────────────────────────


class CajaTipoDocumento(Base):
    """
    Tipo de documento configurable (Factura, Recibo, Nota de Crédito, etc.).

    Extensible por el usuario — pueden agregar nuevos tipos en cualquier momento.
    """

    __tablename__ = "caja_tipo_documentos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)
    descripcion = Column(Text, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<CajaTipoDocumento(nombre='{self.nombre}')>"


class CajaDocumento(Base):
    """
    Documento asociado a movimientos de caja (N:M).

    Un documento puede estar vinculado a múltiples movimientos y viceversa.
    Soporta adjuntos de archivos físicos (PDF, imágenes).
    """

    __tablename__ = "caja_documentos"

    id = Column(Integer, primary_key=True, index=True)
    tipo_documento_id = Column(
        Integer,
        ForeignKey("caja_tipo_documentos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    numero = Column(String(255), nullable=True)
    descripcion = Column(Text, nullable=True)
    fecha_documento = Column(Date, nullable=True)
    monto_documento = Column(Numeric(18, 2), nullable=True)
    # Polymorphic entity linking (future cross-module references)
    entidad_tipo = Column(String(50), nullable=True)
    entidad_id = Column(Integer, nullable=True)
    registrado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    tipo_documento = relationship("CajaTipoDocumento")
    archivos = relationship(
        "CajaArchivo",
        back_populates="documento",
        cascade="all, delete-orphan",
    )
    movimientos = relationship(
        "CajaMovimiento",
        secondary="caja_documento_movimientos",
        back_populates="documentos",
    )
    registrado_por = relationship("Usuario")

    __table_args__ = (Index("ix_caja_doc_entidad", "entidad_tipo", "entidad_id"),)

    def __repr__(self) -> str:
        return f"<CajaDocumento(id={self.id}, tipo_id={self.tipo_documento_id}, numero='{self.numero}')>"


class CajaDocumentoMovimiento(Base):
    """
    Tabla de junction N:M entre documentos y movimientos.
    """

    __tablename__ = "caja_documento_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    documento_id = Column(
        Integer,
        ForeignKey("caja_documentos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movimiento_id = Column(
        Integer,
        ForeignKey("caja_movimientos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("documento_id", "movimiento_id", name="uq_caja_doc_mov"),)


class CajaArchivo(Base):
    """
    Archivo físico adjunto a un documento (PDF, imagen).
    """

    __tablename__ = "caja_archivos"

    id = Column(Integer, primary_key=True, index=True)
    documento_id = Column(
        Integer,
        ForeignKey("caja_documentos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_archivo = Column(String(500), nullable=False)
    ruta_archivo = Column(String(1000), nullable=False)
    tipo_mime = Column(String(100), nullable=False)
    tamanio_bytes = Column(Integer, nullable=True)
    registrado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    documento = relationship("CajaDocumento", back_populates="archivos")
    registrado_por = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<CajaArchivo(id={self.id}, nombre='{self.nombre_archivo}')>"
