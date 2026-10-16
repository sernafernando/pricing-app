"""Frozen per-item cost snapshot (ml-ventas-modo-logistico, PR3, design D4).

Written ONLY by `services/ml_orders_ingestion/costeo_service.py::congelar()`,
INSERT-only via `ON CONFLICT DO NOTHING` (design D5) — a re-ingestion of the
same order/item NEVER rewrites an already-frozen row, so a later ERP cost
change can never leak into a sale that has already been costed. This keeps
the cost seam `MlOrderItemOps` already documents: ingestion of the order/
item rows themselves never reads ERP, and this table is the ONLY place ERP
cost data is joined in.

Nothing reads this table yet in this slice (PR3 is write-only by design —
see the tasks artifact: "merges EARLY... write-only, nothing reads it yet").

`costo_fecha` (added by backfill-costo-congelado-historico): the date the
frozen `costo_origen` is attributable to. NULL for every row THIS module
(`congelar`) writes — the live path reads the CURRENT `ProductoERP.costo`,
which carries no date of its own; `congelado_at` records WHEN we read it,
not what date the value belongs to. Only
`app/scripts/backfill_costo_congelado.py` sets it, to the
`ItemCostListHistory.iclh_cd` of the dated row it actually used, so a
future correction can target exactly the rows a bad backfilled cost came
from instead of re-deriving that from `fuente` alone.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MlOrderItemCosto(Base):
    """One immutable row per (order_id, item_id, variation_id) — the frozen
    cost/IVA/exchange-rate snapshot for that order item at ingestion time."""

    __tablename__ = "ml_order_item_costos"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "item_id",
            "variation_id",
            name="uq_ml_order_item_costos_order_item_variation",
            postgresql_nulls_not_distinct=True,
        ),
        # Every product facet on the Ventas ML screen (marca, subcategoría,
        # PM) reaches the product THROUGH this column -- see migration
        # 20260922_ix_producto_item_id.
        Index("ix_ml_order_item_costos_producto_item_id", "producto_item_id"),
        # TP cost (cost list 8). A NULL `costo_tp_unitario_ars` is the
        # "Total TP incomplete" flag; the backfill and the late-load worker
        # find those rows per product through this partial index -- see
        # migration 20261025_tp_cost_columns.
        Index(
            "ix_ml_order_item_costos_tp_pendiente",
            "producto_item_id",
            postgresql_where=text("costo_tp_unitario_ars IS NULL"),
            sqlite_where=text("costo_tp_unitario_ars IS NULL"),
        ),
        CheckConstraint(
            "(costo_tp_origen IS NULL OR costo_tp_origen >= 0)"
            " AND (costo_tp_tipo_cambio IS NULL OR costo_tp_tipo_cambio >= 0)"
            " AND (costo_tp_unitario_ars IS NULL OR costo_tp_unitario_ars >= 0)",
            name="ck_ml_order_item_costos_tp_no_negativo",
        ),
        # All or nothing: a TP cost is either fully known or fully NULL --
        # never a half-written row that reads like a real one.
        CheckConstraint(
            "(costo_tp_unitario_ars IS NULL) = (costo_tp_origen IS NULL)"
            " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_moneda IS NULL)"
            " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_fuente IS NULL)"
            " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_at IS NULL)",
            name="ck_ml_order_item_costos_tp_completo",
        ),
        # The rate is kept only for a USD price: an ARS TP cost (an ARS
        # list-8 price, or a combo sum already in ARS) carries none.
        CheckConstraint(
            "costo_tp_moneda <> 'ARS' OR costo_tp_tipo_cambio IS NULL",
            name="ck_ml_order_item_costos_tp_ars_sin_tc",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    item_id = Column(String(20), nullable=False, index=True)
    variation_id = Column(BigInteger, nullable=True)

    costo_origen = Column(Numeric(14, 4), nullable=False)
    moneda = Column(String(3), nullable=False)
    tipo_cambio = Column(Numeric(14, 4), nullable=True)
    tipo_cambio_fecha = Column(Date, nullable=True)
    costo_unitario_ars = Column(Numeric(14, 4), nullable=False)

    iva_pct = Column(Numeric(5, 2), nullable=False)
    precio_unitario = Column(Numeric(14, 2), nullable=False)

    # The date `costo_origen` is attributable to. NULL for a live-frozen
    # row (no dated source); the `ItemCostListHistory.iclh_cd` used, for a
    # row written by `app/scripts/backfill_costo_congelado.py`. See the
    # module docstring.
    costo_fecha = Column(Date, nullable=True)

    fuente = Column(String(20), nullable=False)
    producto_item_id = Column(Integer, nullable=False)

    congelado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # TP-Link cost (cost list 8, `tb_item_cost_list.coslis_id = 8`), frozen
    # next to the normal cost for EVERY item regardless of store, so a
    # publication that later moves to the TP store still has it. ALL NULL
    # means "no usable list-8 price" -- that NULL IS the "Total TP
    # incomplete" flag (no separate boolean): never 0, never the normal
    # cost. Written by `congelar()` from the CURRENT list-8 price
    # (`fuente` 'lista8_ingesta' / 'lista8_ingesta_combo'); P2's backfill
    # and late-load worker fill NULL rows once ('lista8_historia' /
    # 'lista8_carga_posterior') and never rewrite a set one.
    costo_tp_origen = Column(Numeric(14, 4), nullable=True)
    costo_tp_moneda = Column(String(3), nullable=True)
    costo_tp_tipo_cambio = Column(Numeric(14, 4), nullable=True)
    costo_tp_unitario_ars = Column(Numeric(14, 4), nullable=True)
    costo_tp_fuente = Column(String(30), nullable=True)
    costo_tp_at = Column(DateTime(timezone=True), nullable=True)
