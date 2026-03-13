"""
Cuenta corriente de empleados — Phase 6.

Sistema de compras de empleados. Los empleados compran productos del inventario ERP
y los montos se trackean en una cuenta corriente, con descuento mensual del sueldo.

Convención de saldo:
- Positivo = el empleado DEBE (deuda)
- Negativo = la empresa debe al empleado (crédito)

Los montos en movimientos son siempre positivos.
El tipo (cargo/abono) determina la dirección.
"""

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Numeric,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TipoMovimientoCC(str, enum.Enum):
    CARGO = "cargo"  # empleado compra → aumenta deuda
    ABONO = "abono"  # pago/deducción mensual → disminuye deuda


class RRHHCuentaCorriente(Base):
    """
    Cabecera de cuenta corriente por empleado.

    Una fila por empleado. El saldo se mantiene denormalizado
    para lecturas rápidas. Se actualiza transaccionalmente con
    cada movimiento.
    """

    __tablename__ = "rrhh_cuenta_corriente"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    saldo = Column(Numeric(15, 2), nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    movimientos = relationship(
        "RRHHCuentaCorrienteMovimiento",
        back_populates="cuenta",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<RRHHCuentaCorriente(empleado_id={self.empleado_id}, saldo={self.saldo})>"


class RRHHCuentaCorrienteMovimiento(Base):
    """
    Movimiento individual de cuenta corriente.

    Cada cargo (compra) o abono (pago/cuota) genera un movimiento.
    Soporta cuotas para compras financiadas.
    """

    __tablename__ = "rrhh_cuenta_corriente_movimiento"

    id = Column(Integer, primary_key=True, index=True)
    cuenta_id = Column(
        Integer,
        ForeignKey("rrhh_cuenta_corriente.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo = Column(String(10), nullable=False)  # cargo / abono
    monto = Column(Numeric(15, 2), nullable=False)  # siempre positivo
    fecha = Column(Date, nullable=False, index=True)
    concepto = Column(String(255), nullable=False)  # "Compra: Auriculares Sony WH-1000XM5"
    descripcion = Column(Text, nullable=True)

    # Referencia a compra (opcional)
    item_id = Column(Integer, nullable=True)  # FK conceptual a tb_item (ERP)
    ct_transaction = Column(Integer, nullable=True)  # FK conceptual a ct_transaction

    # Cuotas
    cuota_numero = Column(Integer, nullable=True)  # 1, 2, 3... (NULL = pago único)
    cuota_total = Column(Integer, nullable=True)  # total de cuotas (NULL = pago único)

    # Saldo después de este movimiento (audit trail)
    saldo_posterior = Column(Numeric(15, 2), nullable=False)

    # --- Auditoría ---
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    cuenta = relationship("RRHHCuentaCorriente", back_populates="movimientos")
    empleado = relationship("RRHHEmpleado")
    registrado_por = relationship("Usuario")

    __table_args__ = (
        Index("idx_cc_mov_empleado_fecha", "empleado_id", "fecha"),
        Index("idx_cc_mov_cuenta_fecha", "cuenta_id", "fecha"),
    )

    def __repr__(self) -> str:
        return f"<RRHHCCMovimiento(id={self.id}, tipo='{self.tipo}', monto={self.monto}, concepto='{self.concepto}')>"
