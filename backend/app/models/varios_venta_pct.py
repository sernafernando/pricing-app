"""The "% de varios" applied to a sale's Total Gauss (ml-ventas-modo-logistico,
PR5, decision recorded in obs #2064 -- no longer blocked).

Deliberately a NEW table, versioned by date, NOT a reuse of
`pricing_constants.varios_porcentaje` (6,5% default): that column is an
ESTIMATE of taxes + financial cost + logistics used to price forward. In a
sale's Total Gauss breakdown those three are already REAL numbers -- the
SIRTAC withholding as a `tax_withholding*` charge, ML's own commission, the
Flex freight from `logistica_costo_cordon`/`costo_override`. Reusing the
estimate would double-count a guessed percentage on top of real data.

Reuses the PATTERN `pricing_constants` already established, not the row:
`fecha_desde`/`fecha_hasta`, the endpoint closes the previous version when a
new one is created (see `api/endpoints/configuracion.py`), and a
`CheckConstraint` mirrors the same date-range invariant.

A sale reads the version VIGENTE AT THE SALE'S DATE, never today's -- the
same rule PR2 already applies to the Flex shipping tariff (a historical
breakdown uses what was in force when the sale happened).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.sql import func

from app.core.database import Base


class VariosVentaPct(Base):
    """One versioned "% de varios" row, valid over `[fecha_desde, fecha_hasta]`
    (open-ended when `fecha_hasta` is `NULL`, meaning "still in force")."""

    __tablename__ = "ml_venta_varios_pct"
    __table_args__ = (
        CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde",
            name="ck_ml_venta_varios_pct_fecha_rango",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    porcentaje = Column(Numeric(5, 2), nullable=False)
    fecha_desde = Column(Date, nullable=False, index=True)
    fecha_hasta = Column(Date, nullable=True)

    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
