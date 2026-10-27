"""Whether one ML tax charge is deducted from a sale's neto or is only
informational, by period (ventas-ml-impuestos-informativos S1, S2).

One row per version of one exact charge name, e.g.
`tax_withholding_sirtac_sobretasa-jujuy`: the name carries the province, so
a surcharge one province stopped charging can be marked informational while
another keeps subtracting. Informational means what SIRTAC always meant:
shown in the breakdown, added back into the neto, out of `neto_sin_iva`.

Versioned like `% de varios` (`varios_venta_pct.py`): `fecha_desde` /
`fecha_hasta`, the endpoint closes the open version of the same name when a
new one starts, and a sale reads the version in force at its own
`date_created`. A charge name with no version keeps the built-in rule
(`breakdown_service.is_recoverable_withholding`).
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class ImpuestoTratamientoVenta(Base):
    """One version of one tax charge's treatment, valid over
    `[fecha_desde, fecha_hasta]` (open-ended when `fecha_hasta` is `NULL`)."""

    __tablename__ = "ml_venta_impuesto_tratamiento"
    __table_args__ = (
        CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde",
            name="ck_ml_venta_impuesto_tratamiento_fecha_rango",
        ),
        UniqueConstraint("charge_name", "fecha_desde", name="uq_ml_venta_impuesto_tratamiento_nombre_desde"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # `ml_payment_charges.name`, verbatim (same length).
    charge_name = Column(String(120), nullable=False, index=True)
    informativo = Column(Boolean, nullable=False)
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=True)

    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
