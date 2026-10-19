"""Sell out: a campaign credit added to profit for every unit sold.

A campaign (`SellOutCampana`) runs between two dates over one or more product
groups (`offset_grupos`, linked through `SellOutCampanaGrupo`). Its credit is
either an amount per unit (`monto_unit` in `moneda`) or a percentage of a base
(`base_porcentaje`: the product cost by default, or the net sale price).

The cap (`tope_unidades` and/or `tope_monto`, in `moneda`) is shared by every
product of the campaign; it is enforced when consumption is written (T7), not
here. Campaigns on the same product and dates stack unless one of them is not
`acumulable`. A campaign is never deleted: it is voided (`anulada`).
"""

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, true

from app.core.database import Base


class SellOutCampana(Base):
    __tablename__ = "sell_out_campanas"
    __table_args__ = (
        CheckConstraint("tipo IN ('por_unidad', 'porcentaje')", name="ck_sell_out_campanas_tipo"),
        CheckConstraint(
            "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL) OR "
            "(tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
            "AND monto_unit IS NULL)",
            name="ck_sell_out_campanas_monto_segun_tipo",
        ),
        CheckConstraint("base_porcentaje IN ('costo', 'precio_neto')", name="ck_sell_out_campanas_base_porcentaje"),
        CheckConstraint("fecha_hasta >= fecha_desde", name="ck_sell_out_campanas_fechas"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_out_campanas_moneda"),
        CheckConstraint("moneda <> 'USD' OR tipo_cambio IS NOT NULL", name="ck_sell_out_campanas_usd_con_tc"),
        CheckConstraint("tipo_cambio IS NULL OR tipo_cambio > 0", name="ck_sell_out_campanas_tc_positivo"),
        CheckConstraint("tope_unidades IS NULL OR tope_unidades > 0", name="ck_sell_out_campanas_tope_unidades"),
        CheckConstraint("tope_monto IS NULL OR tope_monto > 0", name="ck_sell_out_campanas_tope_monto"),
        CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_out_campanas_estado"),
    )

    id = Column(BigInteger, primary_key=True)
    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=False)  # inclusive
    tipo = Column(String(16), nullable=False)
    monto_unit = Column(Numeric(18, 2), nullable=True)  # per unit, in `moneda`
    porcentaje = Column(Numeric(7, 4), nullable=True)
    base_porcentaje = Column(String(16), nullable=False, default="costo", server_default="costo")
    # Currency of `monto_unit` and `tope_monto`; a USD campaign converts at its own fixed rate (ARS per USD).
    moneda = Column(String(3), nullable=False, default="ARS", server_default="ARS")
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    tope_unidades = Column(Integer, nullable=True)
    tope_monto = Column(Numeric(18, 2), nullable=True)
    acumulable = Column(Boolean, nullable=False, default=True, server_default=true())
    estado = Column(String(16), nullable=False, default="activa", server_default="activa")
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Also kept current by the `sell_out_campanas_updated_at` trigger.
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SellOutCampanaGrupo(Base):
    """One product group of a campaign. A group in use by a campaign cannot be deleted (RESTRICT)."""

    __tablename__ = "sell_out_campana_grupos"
    __table_args__ = (
        UniqueConstraint("campana_id", "grupo_id", name="uq_sell_out_campana_grupos_campana_grupo"),
        Index("ix_sell_out_campana_grupos_grupo_id", "grupo_id"),
    )

    id = Column(BigInteger, primary_key=True)
    campana_id = Column(BigInteger, ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), nullable=False)
    grupo_id = Column(Integer, ForeignKey("offset_grupos.id", ondelete="RESTRICT"), nullable=False)
