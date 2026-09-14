"""Persisted deduction amounts of the Total Gauss chain (ml-ventas-modo-logistico,
PR5, design D2).

Written by `services/ml_ventas_desglose/deducciones.py` whenever
`total_gauss` is recomputed for an order. One row per `(order_id, code)` --
`code` is the deduction's registry code (`DeduccionResolver.code`), so the
chain being extensible (design D1: no hardcoded length) does not need a
schema change to grow. `monto` is `NULL` exactly when that deduction was
unknown for that order at `resolved_at` -- never a lying zero.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class MlVentaDeduccion(Base):
    """One row per `(order_id, code)` -- the last-resolved amount of one
    deduction in the Total Gauss chain for that order."""

    __tablename__ = "ml_venta_deducciones"
    __table_args__ = (UniqueConstraint("order_id", "code", name="uq_ml_venta_deducciones_order_code"),)

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    code = Column(String(30), nullable=False)
    orden = Column(Integer, nullable=False)
    # NULL means this deduction was UNKNOWN when resolved -- never Decimal("0").
    monto = Column(Numeric(14, 2), nullable=True)

    resolved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
