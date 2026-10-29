"""Sell out: a campaign credit added to profit for every unit sold.

A campaign (`SellOutCampana`) runs between two dates over one or more product
groups (`offset_grupos`, linked through `SellOutCampanaGrupo`). Its credit is
either an amount per unit (`monto_unit` in `moneda`) or a percentage of a base
(`base_porcentaje`: the product cost by default, or the net sale price).

The cap (`tope_unidades` and/or `tope_monto`, in `moneda`) is ONE cap for the
whole campaign, shared by every product of ALL its groups (owner, 2026-10-19:
routers and switches in one campaign end together once 500 units are sold
between them; separate caps mean separate campaigns). It is enforced when
consumption is written (T7), not here.

FX (`tc_modo`, USD campaigns only; an ARS campaign has `tc_modo` and
`tipo_cambio` NULL):
- `al_cobro` (default for USD): the rate is set later, when the brand pays
  (`tipo_cambio` and `tc_definido_en` set together, changeable and audited).
  Until then every ARS figure is an ESTIMATE at the CURRENT BNA rate (latest
  `tipo_cambio` row for USD, `venta`, kept daily by
  `tipo_cambio_service.actualizar_tipo_cambio_bna`), so it moves with BNA day
  by day; T7 flags it as estimated and recomputes once the rate is set.
- `fijo`: the rate is entered with the campaign and required.
- `dia_venta`: each sale converts at its own day's rate; `tipo_cambio` is NULL.

VAT (owner, 2026-10-20): sell out applies against the net without VAT.
`monto_incluye_iva` says whether `monto_unit` was loaded with VAT; when it was,
each sale's amount is divided by its own product's VAT rate (T7,
`app.services.sell_out.tope`).

A `monto_total` campaign (T26, S34/S35) carries one fixed amount (`monto_total`, in `moneda`, never 0:
positive = a credit, negative = a deduction from profit) and no cap (the total is its cap); the PM or an admin
shares it out by hand per product (`SellOutCampanaItem`), and each product's share spreads over its sales in the
campaign's dates. What nobody was given is "Sin asignar" and counts on `fecha_hasta`.

Campaigns on the same product and dates stack unless one of them is not
`acumulable`. A campaign is never deleted: it is voided (`anulada`).

Per-product amounts (`SellOutCampanaItem`, T22b; legacy grouped offsets): a
`por_unidad` campaign may give a product of its reach its own `monto_unit`
(same currency and VAT flag); the other products get the campaign's. The cap
stays one for all of them.

`offset_origen_id` is the legacy offset (`offsets_ganancia`) a campaign was
migrated from (T15, `app.scripts.migrar_offsets_a_sell_out`), NULL for one
loaded by hand; UNIQUE, so each offset is migrated once. Deleting the offset
keeps the campaign (SET NULL).

`SellOutConsumo` holds what each sale takes from a campaign's cap, rebuilt per
campaign by the T7 allocator; `SellOutDirty` queues the campaigns to rebuild.
`SellOutConsumo.venta_ref` has NO foreign key on purpose, like
`SellInConsumo.venta_ref`: `ml_sale_lines` is deleted and reinserted on every
store, so a physical FK would either block the store or cascade the
consumptions away. The allocator owns that reference; its keyspace is the
channel's (`ml`: `ml_sale_lines.item_row_id`; `fuera` / `tn`: the
`it_transaction` of `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`).
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
from sqlalchemy.sql import false, func, text, true

from app.core.database import Base

# Named so the group-delete endpoint can tell this RESTRICT violation from any other IntegrityError.
FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID = "fk_sell_out_campana_grupos_grupo_id"


class SellOutCampana(Base):
    __tablename__ = "sell_out_campanas"
    __table_args__ = (
        CheckConstraint("tipo IN ('por_unidad', 'porcentaje', 'monto_total')", name="ck_sell_out_campanas_tipo"),
        CheckConstraint(
            "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL "
            "AND monto_total IS NULL) OR "
            "(tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
            "AND monto_unit IS NULL AND monto_total IS NULL) OR "
            "(tipo = 'monto_total' AND monto_total IS NOT NULL AND monto_total <> 0 AND monto_unit IS NULL "
            "AND porcentaje IS NULL AND tope_unidades IS NULL AND tope_monto IS NULL)",
            name="ck_sell_out_campanas_monto_segun_tipo",
        ),
        CheckConstraint("base_porcentaje IN ('costo', 'precio_neto')", name="ck_sell_out_campanas_base_porcentaje"),
        CheckConstraint("fecha_hasta >= fecha_desde", name="ck_sell_out_campanas_fechas"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_out_campanas_moneda"),
        CheckConstraint(
            "(moneda = 'ARS' AND tc_modo IS NULL AND tipo_cambio IS NULL) OR "
            "(moneda = 'USD' AND tc_modo IS NOT NULL AND ("
            "(tc_modo = 'fijo' AND tipo_cambio IS NOT NULL) OR "
            "(tc_modo = 'dia_venta' AND tipo_cambio IS NULL) OR "
            "tc_modo = 'al_cobro'))",
            name="ck_sell_out_campanas_tc_modo",
        ),
        CheckConstraint(
            "(tc_definido_en IS NOT NULL) = (COALESCE(tc_modo, '') = 'al_cobro' AND tipo_cambio IS NOT NULL)",
            name="ck_sell_out_campanas_tc_definido_en",
        ),
        CheckConstraint("tipo_cambio IS NULL OR tipo_cambio > 0", name="ck_sell_out_campanas_tc_positivo"),
        CheckConstraint("tope_unidades IS NULL OR tope_unidades > 0", name="ck_sell_out_campanas_tope_unidades"),
        CheckConstraint("tope_monto IS NULL OR tope_monto > 0", name="ck_sell_out_campanas_tope_monto"),
        CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_out_campanas_estado"),
        UniqueConstraint("offset_origen_id", name="uq_sell_out_campanas_offset_origen_id"),
    )

    id = Column(BigInteger, primary_key=True)
    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=False)  # inclusive
    tipo = Column(String(16), nullable=False)
    monto_unit = Column(Numeric(18, 2), nullable=True)  # per unit, in `moneda`
    porcentaje = Column(Numeric(7, 4), nullable=True)
    # A `monto_total` campaign's whole amount, in `moneda`; negative = a deduction. See the module docstring.
    monto_total = Column(Numeric(18, 2), nullable=True)
    base_porcentaje = Column(String(16), nullable=False, default="costo", server_default="costo")
    # Currency of `monto_unit` and `tope_monto`. USD is the usual case, hence the default.
    moneda = Column(String(3), nullable=False, default="USD", server_default="USD")
    # How a USD campaign converts to ARS (NULL for ARS); see the module docstring.
    tc_modo = Column(String(16), nullable=True)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)  # ARS per USD
    # When an `al_cobro` rate was set (who set it is in the audit rows); NULL otherwise.
    tc_definido_en = Column(DateTime(timezone=True), nullable=True)
    tope_unidades = Column(Integer, nullable=True)
    tope_monto = Column(Numeric(18, 2), nullable=True)
    acumulable = Column(Boolean, nullable=False, default=True, server_default=true())
    # Whether `monto_unit` includes VAT; see the module docstring.
    monto_incluye_iva = Column(Boolean, nullable=False, default=False, server_default=false())
    estado = Column(String(16), nullable=False, default="activa", server_default="activa")
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    # The migrated legacy offset; see the module docstring.
    offset_origen_id = Column(
        Integer,
        ForeignKey("offsets_ganancia.id", ondelete="SET NULL", name="fk_sell_out_campanas_offset_origen_id"),
        nullable=True,
    )
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
    grupo_id = Column(
        Integer,
        ForeignKey("offset_grupos.id", ondelete="RESTRICT", name=FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID),
        nullable=False,
    )


class SellOutCampanaItem(Base):
    """A product's own amount in a campaign: in a `por_unidad` campaign its own `monto_unit` (T22b, legacy grouped
    offsets), replacing the campaign's for that product under the campaign's one cap; in a `monto_total` campaign
    its manual share (T26, S34), `reparto_porcentaje` (a % of the total) or `reparto_monto` (a fixed amount).
    Exactly one of the three per row. Rules that need the campaign row live in the campaigns service: a fixed
    share has the total's sign, shares only on `monto_total` and `monto_unit` only on `por_unidad`. No FK on
    `item_id`, like `SellOutConsumo.item_id`: the campaigns service checks the product is in the campaign's
    reach."""

    __tablename__ = "sell_out_campana_items"
    __table_args__ = (
        UniqueConstraint("campana_id", "item_id", name="uq_sell_out_campana_items_campana_item"),
        CheckConstraint("monto_unit > 0", name="ck_sell_out_campana_items_monto_positivo"),
        CheckConstraint(
            "(monto_unit IS NOT NULL AND reparto_porcentaje IS NULL AND reparto_monto IS NULL) OR "
            "(monto_unit IS NULL AND reparto_porcentaje IS NOT NULL AND reparto_monto IS NULL) OR "
            "(monto_unit IS NULL AND reparto_porcentaje IS NULL AND reparto_monto IS NOT NULL)",
            name="ck_sell_out_campana_items_un_monto",
        ),
        CheckConstraint(
            "reparto_porcentaje > 0 AND reparto_porcentaje <= 100", name="ck_sell_out_campana_items_reparto_porcentaje"
        ),
        CheckConstraint("reparto_monto <> 0", name="ck_sell_out_campana_items_reparto_monto"),
    )

    id = Column(BigInteger, primary_key=True)
    campana_id = Column(BigInteger, ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, nullable=False)
    monto_unit = Column(Numeric(18, 2), nullable=True)  # per unit, in the campaign's `moneda` (por_unidad)
    reparto_porcentaje = Column(Numeric(7, 4), nullable=True)  # % of the total (monto_total)
    reparto_monto = Column(Numeric(18, 2), nullable=True)  # fixed share, in the campaign's `moneda` (monto_total)


class SellOutConsumo(Base):
    """What one sale takes from one campaign's cap (T7). See the module docstring."""

    __tablename__ = "sell_out_consumos"
    __table_args__ = (
        UniqueConstraint("campana_id", "canal", "venta_ref", name="uq_sell_out_consumos_campana_canal_venta"),
        CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_out_consumos_canal"),
        CheckConstraint("unidades > 0", name="ck_sell_out_consumos_unidades_positivas"),
        CheckConstraint("tc_venta IS NULL OR tc_venta > 0", name="ck_sell_out_consumos_tc_venta_positivo"),
        Index("ix_sell_out_consumos_canal_venta", "canal", "venta_ref"),
    )

    id = Column(BigInteger, primary_key=True)
    campana_id = Column(BigInteger, ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), nullable=False)
    canal = Column(String(8), nullable=False)
    venta_ref = Column(BigInteger, nullable=False)  # no FK: see module docstring
    item_id = Column(Integer, nullable=False)  # copy of the sale's product, for lookups by product
    fecha_venta = Column(Date, nullable=False)
    unidades = Column(Integer, nullable=False)
    # In the campaign's `moneda`. Negative only for a negative `monto_total` campaign (no CHECK since 20261214:
    # it cannot see the campaign's type; the allocators keep the other types non-negative).
    monto = Column(Numeric(18, 2), nullable=False)
    # The rate (ARS per USD) the row converts at: `al_cobro` the latest BNA until the campaign's rate is
    # defined, then that rate; `fijo` the campaign's rate; `dia_venta` the BNA on or before the sale day.
    # Rewritten on recompute whenever it changes; NULL for ARS. ARS is computed on read.
    tc_venta = Column(Numeric(18, 6), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SellOutDirty(Base):
    """A campaign waiting for its allocation to be rebuilt (T7). Filled, in the transaction of each change,
    by the campaigns service (load, edit, void, payment rate), the `sell.drain` fan-out of the sale lines it
    drains and the BNA update (`tipo_cambio_service.guardar_cotizacion_bna`); drained by `sell_out.drain`
    (`app.services.sell_out.queue`)."""

    __tablename__ = "sell_out_dirty"

    campana_id = Column(
        BigInteger, ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)
