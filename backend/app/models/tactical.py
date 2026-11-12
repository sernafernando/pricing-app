"""A tactical: the header a brand deal is loaded under, sell in or sell out (tacticals T1, owner 2026-11-04).

Owner: "hay que mejorar el sistema de carga de programa (ahora llamado "tactical") y de campaña" and "el tactical
tiene que podersele cargar una marca adjunta para después poder filtrar por marca". A tactical is only a HEADER: each
of its lines is stored in the existing engines, which carry `tactical_id` (FK RESTRICT: a tactical with children is
never deleted, it is voided), so allocation, FIFO and caps are not rewritten:

- `tipo = 'sell_out'`: each line is a `SellOutCampana` over its own hidden group (`OffsetGrupo.oculto`).
- `tipo = 'sell_in'`: each line is a `SellInBonoMarca` (`base = 'costo_venta'` over products, a brand or a category;
  `base = 'factura'` over one invoice), or a `SellInCompra` for an invoice's fixed total.

`marca` is one of the tactical's brands in `tactical_marcas` (`productos_erp.marca` text the list filters by; owner
2026-11-10: "las marcas que se usan para el filtro hay que hacer un selector multiple"): the one a client sent as
`marca`, else the first. It stays so a reader that knows one brand still gets a valid one. The header's dates, currency, FX, VAT flag and
`acumulable` are copied to every child, which is what the engines read; the header keeps them to show and filter.
`tc_modo` / `tipo_cambio` follow `SellOutCampana`'s FX rules (NULL on ARS). A tactical will be voided (`anulado`)
with all its children, through each engine's own void step. `app.services.tacticals` creates and voids them.

Store scope (tacticals-tienda): `todas_tiendas` means every official store; otherwise `tactical_tiendas` lists the
official `store_id`s and/or synthetic channels `fuera` / `tienda_nube`. `tope_compartido` is independent: false =
one counter per target with the same cap; true = one pool over the selection.
"""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer
from sqlalchemy import Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import false, func, true

from app.core.database import Base

# Also declared by migration `20261105_tacticals` (the schema parity test compares them).
TIPO = "tipo IN ('sell_in', 'sell_out')"
ESTADO = "estado IN ('activo', 'anulado')"
# The CHECK each line engine's table carries (`ck_<table>_tactical_linea`).
TACTICAL_LINEA = "(tactical_id IS NULL AND tactical_linea IS NULL) OR (tactical_id IS NOT NULL AND tactical_linea IS NOT NULL AND tactical_linea >= 1)"
TC_MODO = (
    "(moneda = 'ARS' AND tc_modo IS NULL AND tipo_cambio IS NULL) OR "
    "(moneda = 'USD' AND tc_modo IS NOT NULL AND ("
    "(tc_modo = 'fijo' AND tipo_cambio IS NOT NULL) OR "
    "(tc_modo IN ('dia_venta', 'al_cobro') AND tipo_cambio IS NULL)))"
)
TIENDA_TIPO = "tipo IN ('oficial', 'fuera', 'tienda_nube')"
TIENDA_STORE = "(tipo = 'oficial' AND store_id IS NOT NULL) OR (tipo IN ('fuera', 'tienda_nube') AND store_id IS NULL)"


class Tactical(Base):
    __tablename__ = "tacticals"
    __table_args__ = (
        CheckConstraint(TIPO, name="ck_tacticals_tipo"),
        CheckConstraint(ESTADO, name="ck_tacticals_estado"),
        CheckConstraint("fecha_hasta >= fecha_desde", name="ck_tacticals_fechas"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_tacticals_moneda"),
        CheckConstraint(TC_MODO, name="ck_tacticals_tc_modo"),
        CheckConstraint("tipo_cambio IS NULL OR tipo_cambio > 0", name="ck_tacticals_tc_positivo"),
        Index("ix_tacticals_marca", "marca"),
        Index("ix_tacticals_fechas", "fecha_desde", "fecha_hasta"),
    )

    id = Column(BigInteger, primary_key=True)
    tipo = Column(String(16), nullable=False)
    nombre = Column(String(200), nullable=False)
    marca = Column(String(100), nullable=False)  # productos_erp.marca, exact
    referencia = Column(String(200), nullable=True)  # the brand's own reference, free text
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=False)  # inclusive
    moneda = Column(String(3), nullable=False)
    tc_modo = Column(String(16), nullable=True)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)  # ARS per USD, `fijo` only
    incluye_iva = Column(Boolean, nullable=False, default=False, server_default=false())
    acumulable = Column(Boolean, nullable=False, default=True, server_default=true())
    # Official-store / channel scope (tacticals-tienda). Default matches pre-scope behaviour.
    todas_tiendas = Column(Boolean, nullable=False, default=True, server_default=true())
    # Cap mode over the selected targets: False = same cap, one counter per target; True = one shared pool.
    tope_compartido = Column(Boolean, nullable=False, default=False, server_default=false())
    nota = Column(Text, nullable=True)
    estado = Column(String(16), nullable=False, default="activo", server_default="activo")
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Also kept current by the `tacticals_updated_at` trigger.
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    tiendas = relationship(
        "TacticalTienda",
        back_populates="tactical",
        cascade="all, delete-orphan",
        order_by="TacticalTienda.id",
    )
    marcas = relationship(
        "TacticalMarca",
        back_populates="tactical",
        cascade="all, delete-orphan",
        order_by="TacticalMarca.id",
    )
    cobranza = relationship("TacticalCobranza", back_populates="tactical", uselist=False, cascade="all, delete-orphan")


class TacticalTienda(Base):
    """One store or synthetic channel a tactical applies to when `todas_tiendas` is false (or channels with todas).

    `oficial` rows carry `store_id` → `ml_tiendas_oficiales`. `fuera` / `tienda_nube` never carry a store_id.
    When `todas_tiendas` is true, no `oficial` rows are stored; channel rows may still be present.
    """

    __tablename__ = "tactical_tiendas"
    __table_args__ = (
        CheckConstraint(TIENDA_TIPO, name="ck_tactical_tiendas_tipo"),
        CheckConstraint(TIENDA_STORE, name="ck_tactical_tiendas_store"),
        Index("ix_tactical_tiendas_tactical_id", "tactical_id"),
        Index("ix_tactical_tiendas_store_id", "store_id"),
        # Partial, as migration `20261107_tacticals_tiendas`: channel rows have a NULL store_id, which a plain UNIQUE
        # would not collapse.
        Index(
            "uq_tactical_tiendas_oficial",
            "tactical_id",
            "store_id",
            unique=True,
            postgresql_where=text("tipo = 'oficial'"),
            sqlite_where=text("tipo = 'oficial'"),
        ),
        Index(
            "uq_tactical_tiendas_canal",
            "tactical_id",
            "tipo",
            unique=True,
            postgresql_where=text("tipo IN ('fuera', 'tienda_nube')"),
            sqlite_where=text("tipo IN ('fuera', 'tienda_nube')"),
        ),
    )

    id = Column(BigInteger, primary_key=True)
    tactical_id = Column(BigInteger, ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(16), nullable=False)
    store_id = Column(
        BigInteger,
        ForeignKey("ml_tiendas_oficiales.store_id", ondelete="RESTRICT"),
        nullable=True,
    )

    tactical = relationship("Tactical", back_populates="tiendas")


class TacticalMarca(Base):
    """One brand (`productos_erp.marca`, exact) of a tactical's header, in the order it was entered; the list filter
    matches a tactical when any of them is the filtered brand. Migration `20261110_tacticals_marcas`."""

    __tablename__ = "tactical_marcas"
    __table_args__ = (
        UniqueConstraint("tactical_id", "marca", name="uq_tactical_marcas"),
        Index("ix_tactical_marcas_marca", "marca"),
    )

    id = Column(BigInteger, primary_key=True)
    tactical_id = Column(BigInteger, ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False)
    marca = Column(String(100), nullable=False)

    tactical = relationship("Tactical", back_populates="marcas")


MEDIO = "medio IS NULL OR medio IN ('nota_credito', 'fondo_distribuidor', 'otro')"


class TacticalCobranza(Base):
    """How the brand paid a tactical (tactical cobranza S1, owner 2026-11-10: "fecha de cuando se cobro, si es Nota de
    crédito (ahí número) o si es fondo en distribuidor (ahí un panel para aclarar el distri) u otro ... que obligatorio
    sea la fecha no más"). At most one per tactical: a tactical with a row is "Cobrado", without one "Pendiente"; undo
    deletes the row. Only `fecha_cobro` is required; `nc_numero` / `distribuidor` / `otro_detalle` go with their
    `medio`. Migration `20261110_tactical_cobranza`."""

    __tablename__ = "tactical_cobranzas"
    __table_args__ = (
        UniqueConstraint("tactical_id", name="uq_tactical_cobranzas_tactical"),
        CheckConstraint(MEDIO, name="ck_tactical_cobranzas_medio"),
        Index("ix_tactical_cobranzas_usuario_id", "usuario_id"),
    )

    id = Column(BigInteger, primary_key=True)
    tactical_id = Column(BigInteger, ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False)
    fecha_cobro = Column(Date, nullable=False)
    medio = Column(String(32), nullable=True)
    nc_numero = Column(String(100), nullable=True)
    distribuidor = Column(String(200), nullable=True)
    otro_detalle = Column(String(500), nullable=True)
    observaciones = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)  # last to save it
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    tactical = relationship("Tactical", back_populates="cobranza")


FACTURA_PENDIENTE_ESTADO = "estado IN ('pendiente', 'aplicada', 'anulada')"
# Applied: it names the purchase it became; otherwise it has none.
FACTURA_PENDIENTE_COMPRA = "(estado = 'aplicada') = (compra_id IS NOT NULL)"


class TacticalFacturaPendiente(Base):
    """A sell in invoice line with a fixed total saved before Compras linked its operation's supplier invoice (sell in
    factura pendiente, owner 2026-11-12: "la carga con factura de sell in tiene que poder cargarse y aplicar recién
    cuando se agregue una factura no al revés"). It applies nothing while `pendiente`; once the operation has its
    invoice date and invoiced lines, the `sell_in.bono` worker builds the purchase with the same code a tactical loaded
    with the invoice uses (`app.services.tacticals.aplicar_facturas_pendientes`) and the row becomes `aplicada`, naming
    it. Voiding the tactical makes it `anulada`; a full replace deletes the lines it does not keep. It keeps what that
    purchase needs from the line: total, currency, the tactical's fixed rate (USD) and description. Migration
    `20261112_tactical_facturas_pendientes`."""

    __tablename__ = "tactical_facturas_pendientes"
    __table_args__ = (
        CheckConstraint(FACTURA_PENDIENTE_ESTADO, name="ck_tactical_facturas_pendientes_estado"),
        CheckConstraint(FACTURA_PENDIENTE_COMPRA, name="ck_tactical_facturas_pendientes_compra"),
        CheckConstraint("tactical_linea >= 1", name="ck_tactical_facturas_pendientes_linea"),
        CheckConstraint("valor > 0", name="ck_tactical_facturas_pendientes_valor"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_tactical_facturas_pendientes_moneda"),
        Index("ix_tactical_facturas_pendientes_tactical_id", "tactical_id"),
        # The queue gate and the worker look for an operation's waiting rows.
        Index(
            "ix_tactical_facturas_pendientes_pedido_pendiente",
            "pedido_id",
            postgresql_where=text("estado = 'pendiente'"),
        ),
        Index("ix_tactical_facturas_pendientes_compra_id", "compra_id"),
        Index("ix_tactical_facturas_pendientes_usuario_id", "usuario_id"),
    )

    id = Column(BigInteger, primary_key=True)
    tactical_id = Column(BigInteger, ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False)
    tactical_linea = Column(Integer, nullable=False)
    pedido_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False)
    valor = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)  # the tactical's fixed rate of a USD line; NULL on ARS
    descripcion = Column(Text, nullable=True)
    estado = Column(String(16), nullable=False, server_default=text("'pendiente'"))
    compra_id = Column(BigInteger, ForeignKey("sell_in_compras.id", ondelete="RESTRICT"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    aplicada_en = Column(DateTime(timezone=True), nullable=True)
