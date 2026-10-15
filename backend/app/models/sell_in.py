"""Sell in: a purchase discount that lowers the cost of the units it covers.

A sell-in purchase (`SellInCompra`) carries the discount total, its currency
and the formula used to split it across its items (`SellInCompraItem`). Every
sold unit that uses up part of an item's discount is recorded as a consumption
(`SellInConsumo`), so the discount applies only to that purchase's units.

`SellInConsumo.venta_ref` has NO foreign key on purpose: `ml_sale_lines` is
deleted and reinserted on every store, so a physical FK would either block the
store or cascade the consumptions away. The allocator owns that reference.
"""

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.sql import func

from app.core.database import Base


class SellInCompra(Base):
    __tablename__ = "sell_in_compras"
    __table_args__ = (
        CheckConstraint("cuenta_desde IN ('compra', 'ingreso')", name="ck_sell_in_compras_cuenta_desde"),
        CheckConstraint(
            "cuenta_desde <> 'ingreso' OR fecha_ingreso IS NOT NULL", name="ck_sell_in_compras_ingreso_con_fecha"
        ),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_in_compras_moneda"),
        CheckConstraint("monto_total > 0", name="ck_sell_in_compras_monto_positivo"),
        CheckConstraint("moneda <> 'USD' OR tipo_cambio IS NOT NULL", name="ck_sell_in_compras_usd_con_tc"),
        CheckConstraint("tipo_cambio IS NULL OR tipo_cambio > 0", name="ck_sell_in_compras_tc_positivo"),
        CheckConstraint("formula IN ('proporcional', 'por_unidad', 'manual')", name="ck_sell_in_compras_formula"),
        CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_in_compras_estado"),
    )

    id = Column(BigInteger, primary_key=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id", ondelete="RESTRICT"), nullable=True, index=True)
    pedido_compra_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="SET NULL"), nullable=True)
    fecha_compra = Column(Date, nullable=False)
    fecha_ingreso = Column(Date, nullable=True)
    # Which date starts counting units: the purchase date (default) or the goods receipt.
    cuenta_desde = Column(String(16), nullable=False, default="compra", server_default="compra")
    moneda = Column(String(3), nullable=False)
    monto_total = Column(Numeric(18, 2), nullable=False)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    formula = Column(String(16), nullable=False, default="proporcional", server_default="proporcional")
    estado = Column(String(16), nullable=False, default="activa", server_default="activa")
    descripcion = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Also kept current by the `sell_in_compras_updated_at` trigger, so raw SQL updates refresh it too.
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SellInCompraItem(Base):
    __tablename__ = "sell_in_compra_items"
    __table_args__ = (
        UniqueConstraint("compra_id", "item_id", name="uq_sell_in_compra_items_compra_item"),
        CheckConstraint("cantidad > 0", name="ck_sell_in_compra_items_cantidad_positiva"),
        CheckConstraint("monto_asignado >= 0", name="ck_sell_in_compra_items_monto_no_negativo"),
        CheckConstraint("costo_base_unit >= 0", name="ck_sell_in_compra_items_costo_no_negativo"),
    )

    id = Column(BigInteger, primary_key=True)
    compra_id = Column(BigInteger, ForeignKey("sell_in_compras.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), nullable=False, index=True)
    cantidad = Column(Integer, nullable=False)
    # Plain unit cost frozen when the purchase is loaded, in the purchase currency.
    costo_base_unit = Column(Numeric(18, 6), nullable=False)
    monto_asignado = Column(Numeric(18, 2), nullable=False)


class SellInConsumo(Base):
    __tablename__ = "sell_in_consumos"
    __table_args__ = (
        UniqueConstraint("canal", "venta_ref", "compra_item_id", name="uq_sell_in_consumos_canal_venta_item"),
        CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_in_consumos_canal"),
        CheckConstraint("unidades > 0", name="ck_sell_in_consumos_unidades_positivas"),
        CheckConstraint("descuento_ars >= 0", name="ck_sell_in_consumos_descuento_no_negativo"),
        Index("ix_sell_in_consumos_item_fecha", "item_id", "fecha_venta"),
        Index("ix_sell_in_consumos_compra_item_id", "compra_item_id"),
    )

    id = Column(BigInteger, primary_key=True)
    compra_item_id = Column(BigInteger, ForeignKey("sell_in_compra_items.id", ondelete="CASCADE"), nullable=False)
    canal = Column(String(8), nullable=False)
    venta_ref = Column(BigInteger, nullable=False)  # no FK: see module docstring
    item_id = Column(Integer, nullable=False)  # copy of the line's item, for lookups by product
    fecha_venta = Column(Date, nullable=False)
    unidades = Column(Integer, nullable=False)
    descuento_ars = Column(Numeric(18, 2), nullable=False)
