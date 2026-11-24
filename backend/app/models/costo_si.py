"""Costo SI storage (sell-in-costo-si T2, migrations 20261125_costo_si and 20261125_costo_si_drop_full).

- `costo_si_pasos`: every product's history, one row per step (its start, then one per purchase invoice). The row is
  the average in force from `fecha` on, with its breakdown: net, each sell in %, net-net, stock before, average after
  (5 decimals, S10) in the product's cost currency, `moneda` (L18). The current costo SI is the product's last row.
- `costo_si_backups`: the rows a recompute replaced, before it replaced them (S8, L2.5 / L4.8).
- `costo_si_dirty`: the products to recompute and from which date; drained by `sell.drain`, no cron.
- `costo_si_stock_diario`: the daily photo of AVAILABLE stock, principal (GBP) and Full (Mercado Libre), so the
  reconstruction is only needed for the past (S3 decision).
- `costo_si_factura_tc`: a PM's FX correction for one purchase invoice (S4, L4.5).
- `costo_si_compras_sospechosas`: purchases whose price is suspicious against the costo SI right before them (owner
  L29, migration 20261129_costo_si_compras_sospechosas), held out of the average until a reviewer accepts them.
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
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

USD = Numeric(18, 5)


class CostoSiPaso(Base):
    __tablename__ = "costo_si_pasos"
    __table_args__ = (
        UniqueConstraint("item_id", "orden", name="uq_costo_si_pasos_item_orden"),
        Index("ix_costo_si_pasos_item_fecha", "item_id", "fecha"),
    )

    id = Column(BigInteger, primary_key=True)
    item_id = Column(Integer, nullable=False)
    orden = Column(Integer, nullable=False)  # 0 = the start, then the purchases in order
    tipo = Column(String(8), nullable=False)  # 'inicio' | 'compra' | 'lista' (L23)
    fecha = Column(Date, nullable=False)  # in force from this date on
    ct_transaction = Column(BigInteger, nullable=True)  # the purchase invoice; NULL on the start
    cantidad = Column(Integer, nullable=False)
    costo_neto_usd = Column(USD, nullable=True)
    sell_ins = Column(JSONB, nullable=False, server_default=text("'[]'"))  # [{origen, ref, porcentaje}]
    sell_in_pct = Column(Numeric(9, 4), nullable=False, server_default=text("0"))
    costo_neto_neto_usd = Column(USD, nullable=True)
    stock_antes = Column(Integer, nullable=False)
    stock_base = Column(Integer, nullable=False)
    stock_despues = Column(Integer, nullable=False)
    promedio_usd = Column(USD, nullable=True)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    fuente_tc = Column(String(16), nullable=True)
    en_compras = Column(Boolean, nullable=False, server_default=text("false"))
    # The product's cost currency the step is in (owner L18, migration 20261126_costo_si_moneda): the `*_usd`
    # columns kept their names and hold amounts in this currency.
    moneda = Column(String(3), nullable=False, server_default=text("'USD'"))
    calculado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostoSiBackup(Base):
    __tablename__ = "costo_si_backups"
    __table_args__ = (Index("ix_costo_si_backups_item", "item_id", "created_at"),)

    id = Column(BigInteger, primary_key=True)
    item_id = Column(Integer, nullable=False)
    desde = Column(Date, nullable=True)  # the first date whose value changed
    motivo = Column(Text, nullable=False)
    pasos = Column(JSONB, nullable=False)  # the replaced rows, as they were
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostoSiDirty(Base):
    __tablename__ = "costo_si_dirty"

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    desde = Column(Date, nullable=True)  # earliest date a change touched; NULL: unknown (whole history)
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)


class CostoSiStockDiario(Base):
    __tablename__ = "costo_si_stock_diario"
    __table_args__ = (PrimaryKeyConstraint("fecha", "item_id", name="pk_costo_si_stock_diario"),)

    fecha = Column(Date, nullable=False)
    item_id = Column(Integer, nullable=False)
    principal = Column(Integer, nullable=False)  # GBP depot 1 available
    full = Column(Integer, nullable=False)  # Mercado Libre Full available
    tomado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostoSiFacturaTc(Base):
    __tablename__ = "costo_si_factura_tc"

    ct_transaction = Column(BigInteger, primary_key=True, autoincrement=False)
    tipo_cambio = Column(Numeric(18, 6), nullable=False)
    usuario_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostoSiCompraSospechosa(Base):
    """One suspicious purchase (owner L29): a product on a purchase invoice whose net unit price is below 1/10 or
    above 10x the costo SI right before it (or its list cost when there is none). Written by the recompute
    (`costo_si.sospechas.reconciliar`), decided by a reviewer: 'pendiente' and 'excluida' keep it out of the average,
    'aceptada' lets it in. A change of `estado` requeues the product from `fecha` (trigger in that migration)."""

    __tablename__ = "costo_si_compras_sospechosas"
    __table_args__ = (
        UniqueConstraint("item_id", "ct_transaction", name="uq_costo_si_compras_sospechosas_item_ct"),
        CheckConstraint(
            "estado IN ('pendiente', 'aceptada', 'excluida')", name="ck_costo_si_compras_sospechosas_estado"
        ),
        Index("ix_costo_si_compras_sospechosas_estado_fecha", "estado", "fecha"),
        Index("ix_costo_si_compras_sospechosas_revisado_por", "revisado_por"),
    )

    id = Column(BigInteger, primary_key=True)
    item_id = Column(Integer, nullable=False)
    ct_transaction = Column(BigInteger, nullable=False)  # the purchase invoice
    fecha = Column(Date, nullable=False)  # its supplier invoice date
    cantidad = Column(Integer, nullable=False)
    precio = Column(USD, nullable=False)  # net unit price in `moneda`, before sell ins, as evaluated
    moneda = Column(String(3), nullable=False)  # the product's cost currency (L18)
    precio_factura = Column(Numeric(18, 6), nullable=False)  # the unit price as loaded on the invoice
    moneda_factura = Column(String(3), nullable=False)  # the invoice's currency
    tipo_cambio = Column(Numeric(18, 6), nullable=True)  # the rate `precio_factura` was converted at; None if same
    referencia = Column(USD, nullable=False)  # the cost it was checked against
    fuente_ref = Column(String(8), nullable=False)  # 'costo_si' | 'lista'
    ratio = Column(Numeric(18, 6), nullable=False)  # precio / referencia
    estado = Column(String(10), nullable=False, server_default=text("'pendiente'"))  # pendiente|aceptada|excluida
    detectada_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revisado_por = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    revisado_at = Column(DateTime(timezone=True), nullable=True)
    nota = Column(Text, nullable=True)
