"""Sell in: a purchase discount that lowers the cost of the units it covers.

A sell-in purchase (`SellInCompra`) carries the discount total, its currency
and the formula used to split it across its items (`SellInCompraItem`). Every
sold unit that uses up part of an item's discount is recorded as a consumption
(`SellInConsumo`), so the discount applies only to that purchase's units.

A brand bonus (`SellInBonoMarca`) pays an amount per invoiced unit of one
brand over a supplier-invoice date range. It is not a purchase itself: the
`sell_in.bono` worker generates and maintains one `SellInCompra` per (bonus,
Compras operation) from the operation's invoiced lines (`origen =
'bono_marca'`, `bono_id`, `bono_pedido_id`); manual purchases have `origen =
'manual'` and are never touched by it. `SellInBonoDirty` is its work queue.

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
from sqlalchemy.sql import func, text

from app.core.database import Base


class SellInBonoMarca(Base):
    """X per invoiced unit (or a % of the invoiced net) of the products in the bonus's scope, for the
    Compras operations whose supplier invoice date (`pedidos_compra.fecha_factura`) falls in
    [`fecha_desde`, `fecha_hasta`]. Never deleted: voided.

    The scope (`alcance`) is a brand (`marca`), a category (`categoria`), some models
    (`SellInBonoItem` rows) or one invoice (`pedido_id`); each carries only its own field. The table
    keeps its brand-bonus name. The reconcile (`app.services.sell_in.bonos`) and the API read every
    scope and kind (T3e-2, T3e-3), and its shared cap (T24)."""

    __tablename__ = "sell_in_bonos_marca"
    __table_args__ = (
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_in_bonos_marca_moneda"),
        CheckConstraint("fecha_desde <= fecha_hasta", name="ck_sell_in_bonos_marca_rango"),
        CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_in_bonos_marca_estado"),
        CheckConstraint(
            "alcance IN ('marca', 'categoria', 'modelos', 'factura')", name="ck_sell_in_bonos_marca_alcance"
        ),
        CheckConstraint(
            "(alcance = 'marca' AND marca IS NOT NULL AND categoria IS NULL AND pedido_id IS NULL) "
            "OR (alcance = 'categoria' AND categoria IS NOT NULL AND marca IS NULL AND pedido_id IS NULL) "
            "OR (alcance = 'modelos' AND marca IS NULL AND categoria IS NULL AND pedido_id IS NULL) "
            "OR (alcance = 'factura' AND marca IS NULL AND categoria IS NULL)",
            name="ck_sell_in_bonos_marca_campos_segun_alcance",
        ),
        CheckConstraint("tipo IN ('por_unidad', 'porcentaje')", name="ck_sell_in_bonos_marca_tipo"),
        CheckConstraint(
            "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL) "
            "OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
            "AND monto_unit IS NULL)",
            name="ck_sell_in_bonos_marca_monto_segun_tipo",
        ),
        CheckConstraint("tope_unidades IS NULL OR tope_unidades > 0", name="ck_sell_in_bonos_marca_tope_unidades"),
        CheckConstraint("tope_monto IS NULL OR tope_monto > 0", name="ck_sell_in_bonos_marca_tope_monto"),
    )

    id = Column(BigInteger, primary_key=True)
    alcance = Column(String(16), nullable=False, default="marca", server_default="marca")
    marca = Column(String(100), nullable=True, index=True)  # productos_erp.marca, exact ('marca' scope)
    categoria = Column(String(100), nullable=True)  # productos_erp.categoria, exact ('categoria' scope)
    # The operation of a 'factura' bonus. Deleting it keeps the bonus (NULL); the worker voids what it generated.
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="SET NULL", name="fk_sell_in_bonos_marca_pedido_id"),
        nullable=True,
        index=True,
    )
    # 'por_unidad' (`monto_unit` per invoiced unit) or 'porcentaje' (`porcentaje` of the invoiced net).
    tipo = Column(String(16), nullable=False, default="por_unidad", server_default="por_unidad")
    monto_unit = Column(Numeric(18, 2), nullable=True)  # per invoiced unit, in `moneda`
    porcentaje = Column(Numeric(7, 4), nullable=True)
    moneda = Column(String(3), nullable=False)
    fecha_desde = Column(Date, nullable=False)  # supplier invoice date, inclusive
    fecha_hasta = Column(Date, nullable=False)  # inclusive
    # One cap shared by every product and operation the bonus reaches (T24): invoiced units and/or money in
    # `moneda`; NULL: no cap. The reconcile allocates it like sell out's (`sell_out.tope`).
    tope_unidades = Column(Integer, nullable=True)
    tope_monto = Column(Numeric(18, 2), nullable=True)
    descripcion = Column(Text, nullable=True)
    estado = Column(String(16), nullable=False, default="activa", server_default="activa")
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Also kept current by the `sell_in_bonos_marca_updated_at` trigger.
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SellInBonoItem(Base):
    """A model (`item_id`) reached by a 'modelos' bonus. No FK to `productos_erp`: the ERP may hold an item
    the catalog sync has not brought yet (like `pedido_compra_lineas_facturadas`).

    A model may carry its own value (T23a, legacy grouped offsets): `monto_unit` on a 'por_unidad' bonus or
    `porcentaje` on a 'porcentaje' one replaces the bonus's for that model; NULL takes the bonus's."""

    __tablename__ = "sell_in_bono_items"
    __table_args__ = (
        UniqueConstraint("bono_id", "item_id", name="uq_sell_in_bono_items_bono_item"),
        CheckConstraint("monto_unit IS NULL OR monto_unit > 0", name="ck_sell_in_bono_items_monto_positivo"),
        CheckConstraint(
            "porcentaje IS NULL OR (porcentaje > 0 AND porcentaje <= 100)",
            name="ck_sell_in_bono_items_porcentaje_rango",
        ),
        CheckConstraint("monto_unit IS NULL OR porcentaje IS NULL", name="ck_sell_in_bono_items_un_valor"),
    )

    id = Column(BigInteger, primary_key=True)
    bono_id = Column(BigInteger, ForeignKey("sell_in_bonos_marca.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, nullable=False, index=True)
    monto_unit = Column(Numeric(18, 2), nullable=True)  # like SellInBonoMarca.monto_unit
    porcentaje = Column(Numeric(7, 4), nullable=True)  # like SellInBonoMarca.porcentaje


class SellInBonoDirty(Base):
    """What the `sell_in.bono` worker must reconcile: a bonus (`tipo = 'bono'`, `ref` = its id) or a
    Compras operation (`tipo = 'pedido'`, `ref` = `pedidos_compra.id`). Filled by row triggers
    (`app.services.sell_in.bono_queue`); a new change re-queues a row in place (attempts reset)."""

    __tablename__ = "sell_in_bono_dirty"
    __table_args__ = (CheckConstraint("tipo IN ('bono', 'pedido')", name="ck_sell_in_bono_dirty_tipo"),)

    tipo = Column(String(8), primary_key=True)
    ref = Column(BigInteger, primary_key=True, autoincrement=False)
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)


class SellInCompra(Base):
    __tablename__ = "sell_in_compras"
    __table_args__ = (
        CheckConstraint("origen IN ('manual', 'bono_marca')", name="ck_sell_in_compras_origen"),
        CheckConstraint(
            "(origen = 'manual' AND bono_id IS NULL AND bono_pedido_id IS NULL) "
            "OR (origen = 'bono_marca' AND bono_id IS NOT NULL)",
            name="ck_sell_in_compras_origen_bono",
        ),
        # One generated purchase per (bonus, operation). An operation deleted later leaves
        # `bono_pedido_id` NULL (the worker voids that orphan), so NULLs never collide.
        Index(
            "uq_sell_in_compras_bono_pedido",
            "bono_id",
            "bono_pedido_id",
            unique=True,
            postgresql_where=text("bono_id IS NOT NULL"),
            sqlite_where=text("bono_id IS NOT NULL"),
        ),
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
        CheckConstraint("tipo IN ('monto', 'porcentaje')", name="ck_sell_in_compras_tipo"),
        CheckConstraint(
            "(tipo = 'monto' AND porcentaje IS NULL) "
            "OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100)",
            name="ck_sell_in_compras_porcentaje_segun_tipo",
        ),
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
    # 'monto' (a fixed amount) or 'porcentaje' (a % of the invoiced net); `monto_total` is set either way.
    tipo = Column(String(16), nullable=False, default="monto", server_default="monto")
    porcentaje = Column(Numeric(7, 4), nullable=True)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    formula = Column(String(16), nullable=False, default="proporcional", server_default="proporcional")
    estado = Column(String(16), nullable=False, default="activa", server_default="activa")
    descripcion = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    # 'manual' (loaded by an operator) or 'bono_marca' (generated by the `sell_in.bono` worker).
    origen = Column(String(16), nullable=False, default="manual", server_default="manual")
    bono_id = Column(BigInteger, ForeignKey("sell_in_bonos_marca.id", ondelete="RESTRICT"), nullable=True)
    # The operation a generated purchase belongs to; its own column (not `pedido_compra_id`, due to be dropped).
    bono_pedido_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Also kept current by the `sell_in_compras_updated_at` trigger, so raw SQL updates refresh it too.
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SellInCompraPedido(Base):
    """Links a sell-in purchase to one Compras operation (`pedidos_compra`).

    A purchase can link several operations (same supplier and currency, checked
    by the service), and one operation can serve several purchases, so there is
    no unique on `pedido_compra_id` alone. The old `SellInCompra.pedido_compra_id`
    column still holds the first operation until it is dropped. Deleting an
    operation removes its link only; the purchase keeps its items.
    """

    __tablename__ = "sell_in_compra_pedidos"
    __table_args__ = (
        UniqueConstraint("compra_id", "pedido_compra_id", name="uq_sell_in_compra_pedidos_compra_pedido"),
        Index("ix_sell_in_compra_pedidos_pedido_compra_id", "pedido_compra_id"),
    )

    id = Column(BigInteger, primary_key=True)
    compra_id = Column(BigInteger, ForeignKey("sell_in_compras.id", ondelete="CASCADE"), nullable=False)
    pedido_compra_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
