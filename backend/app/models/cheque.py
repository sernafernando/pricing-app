"""
Modelos SQLAlchemy — Módulo de Cheques (Slice 1).

Tablas:
  - chequeras: libretas de cheques de banco propio.
  - cheques: cheques propios y de terceros (esquema completo para todos los slices).
  - orden_pago_cheque: tabla de enlace cheque↔OP.
  - cheque_evento: auditoría append-only del ciclo de vida del cheque.

Referencias:
  - openspec/changes/compras-cheques/design.md (modelo de datos + máquina de estados)
  - openspec/changes/compras-cheques/tasks.md T1.2
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Chequera(Base):
    """Libreta/talonario de cheques asociada a un banco propio (tipo fisico o echeq)."""

    __tablename__ = "chequeras"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    banco_empresa_id = Column(Integer, ForeignKey("bancos_empresa.id", ondelete="RESTRICT"), nullable=False)
    descripcion = Column(String(120), nullable=True)
    instrumento = Column(String(10), nullable=False, default="fisico")
    numero_desde = Column(BigInteger, nullable=True)
    numero_hasta = Column(BigInteger, nullable=True)
    proximo_numero = Column(BigInteger, nullable=True)
    activa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_by = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)

    # Relationships
    banco_empresa = relationship("BancoEmpresa", foreign_keys=[banco_empresa_id])
    cheques = relationship("Cheque", back_populates="chequera")

    __table_args__ = (
        CheckConstraint("instrumento IN ('fisico', 'echeq')", name="ck_chequera_instrumento"),
        Index("ix_chequera_banco", "banco_empresa_id"),
    )


class Cheque(Base):
    """Cheque propio o de tercero. Esquema completo para todos los slices.

    Campos propios (Slice 1): banco_empresa_id, chequera_id.
    Campos de terceros (Slice 2): banco_nombre, cuit_librador, librador_nombre.
    Campos OP: proveedor_id, orden_pago_id (denormalizado).
    """

    __tablename__ = "cheques"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Identidad
    tipo = Column(String(10), nullable=False)  # 'propio' | 'tercero'
    instrumento = Column(String(10), nullable=False, default="fisico")  # 'fisico' | 'echeq'
    estado = Column(String(20), nullable=False)

    # Datos del cheque
    numero = Column(String(40), nullable=False)
    monto = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="ARS")
    fecha_emision = Column(Date, nullable=False)
    fecha_pago = Column(Date, nullable=False)
    es_diferido = Column(Boolean, nullable=False, default=False)

    # Propios
    banco_empresa_id = Column(Integer, ForeignKey("bancos_empresa.id", ondelete="RESTRICT"), nullable=True)
    chequera_id = Column(BigInteger, ForeignKey("chequeras.id", ondelete="RESTRICT"), nullable=True)

    # Terceros
    banco_nombre = Column(String(120), nullable=True)
    cuit_librador = Column(String(13), nullable=True)
    librador_nombre = Column(String(160), nullable=True)

    # Pago / imputación
    proveedor_id = Column(Integer, ForeignKey("proveedores.id", ondelete="RESTRICT"), nullable=True)
    orden_pago_id = Column(Integer, ForeignKey("ordenes_pago.id", ondelete="SET NULL"), nullable=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_by = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    motivo_anulacion = Column(Text, nullable=True)

    # Relationships
    chequera = relationship("Chequera", back_populates="cheques")
    banco_empresa = relationship("BancoEmpresa", foreign_keys=[banco_empresa_id])
    eventos = relationship("ChequeEvento", back_populates="cheque", order_by="ChequeEvento.id")

    __table_args__ = (
        CheckConstraint("tipo IN ('propio', 'tercero')", name="ck_cheque_tipo"),
        CheckConstraint("instrumento IN ('fisico', 'echeq')", name="ck_cheque_instrumento"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_cheque_moneda"),
        CheckConstraint("fecha_pago >= fecha_emision", name="ck_cheque_fechas"),
        # Unicidad numero por chequera — índice parcial (solo filas con chequera_id NOT NULL)
        Index(
            "uq_cheque_chequera_numero",
            "chequera_id",
            "numero",
            unique=True,
            postgresql_where=text("chequera_id IS NOT NULL"),
        ),
        # Índices
        Index("ix_cheque_tipo_estado", "tipo", "estado"),
        Index("ix_cheque_proveedor", "proveedor_id"),
        Index("ix_cheque_estado_fecha_pago", "estado", "fecha_pago"),
        Index("ix_cheque_banco_empresa", "banco_empresa_id"),
    )


class OrdenPagoCheque(Base):
    """Tabla de enlace entre una OP y el/los cheques que la cubren.

    Un cheque solo puede cubrir UNA OP activa (UNIQUE cheque_id).
    Permite que una OP combine N cheques + caja + banco.
    monto_op_moneda: cobertura derivada a moneda de la OP (por TC si cross-moneda).
    """

    __tablename__ = "orden_pago_cheque"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    orden_pago_id = Column(Integer, ForeignKey("ordenes_pago.id", ondelete="RESTRICT"), nullable=False)
    cheque_id = Column(BigInteger, ForeignKey("cheques.id", ondelete="RESTRICT"), nullable=False, unique=True)
    monto_op_moneda = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    cheque = relationship("Cheque")

    __table_args__ = (Index("ix_opc_orden_pago", "orden_pago_id"),)


class ChequeEvento(Base):
    """Registro append-only de hechos del ciclo de vida de un cheque.

    Tipos: emitido, entregado, depositado, debitado, acreditado,
    rechazado, anulado, aceptado, en_custodia, imputado_cc, revertido_cc.

    Un módulo GL futuro puede consumir estos eventos sin tocar el módulo de cheques.
    """

    __tablename__ = "cheque_evento"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cheque_id = Column(BigInteger, ForeignKey("cheques.id", ondelete="RESTRICT"), nullable=False)
    tipo = Column(String(30), nullable=False)
    payload = Column(JSON, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    cheque = relationship("Cheque", back_populates="eventos")

    __table_args__ = (Index("ix_cheque_evento_cheque", "cheque_id"),)
