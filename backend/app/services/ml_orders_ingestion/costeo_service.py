"""Frozen per-item cost snapshot writer (ml-ventas-modo-logistico, PR3).

`congelar()` is called from `ingestion_service.upsert_order` AFTER
`_upsert_item_row` for every item on the order (design D4/D5). It is
INSERT-only via `ON CONFLICT DO NOTHING` on `(order_id, item_id,
variation_id)`: a re-ingestion of an order that was already costed NEVER
rewrites the frozen snapshot, even if the ERP cost, its IVA rate, or the
exchange rate changed since — see the module docstring on
`models/ml_order_item_costo.py`.

Linkage (design D6): ML `item_id` is an MLA string
(`MlOrderItemOps.item_id` / `OrderItemOpsDTO.item_id`); `ProductoERP.item_id`
is an ERP integer. They are NEVER joined directly. The path is:

    item.item_id (MLA) -> PublicacionML.mla -> PublicacionML.item_id (int)
                                                        -> ProductoERP.item_id

with a fallback when no publication links that MLA:

    item.seller_sku -> ProductoERP.codigo

Absence at any step means UNKNOWN -- no row is written for that item. So
does a cost that is not a REAL cost once a product IS found: `NULL` OR
`<= 0`, because `erp_sync` reads the cost with a `0` default and never
writes `NULL` there (see `tiene_costo_propio`). A product with no cost row
in the ERP -- a pack/combo/kit is the dominant case -- arrives as `0.0`,
and freezing that zero would report the goods as free. Such a product is
costed from its components instead when the ERP knows its bill of
materials (`componentes_por_combo`), and left uncosted when it does not.
`Decimal(str(...))` conversion
happens HERE, at the first read of `ProductoERP.costo`/`.iva` (both `Float`
columns) -- never later in the chain (money-path Decimal discipline).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.tb_item_association import TbItemAssociation
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO
from app.services.tn_publish_core.resolve import (
    latest_usd_rate_with_date,
)

logger = logging.getLogger(__name__)

# WHICH of design D6's two linkage paths resolved the product. Stamping a
# single `"erp"` for both made the column useless for the one question it
# gets asked: when a cost looks wrong, was it the authoritative publication
# link or the SKU fallback that picked this product?
FUENTE_PUBLICACION = "erp_publicacion"
FUENTE_SKU = "erp_sku"

# Written ONLY by `app/scripts/backfill_costo_congelado.py`, NEVER by
# `congelar()` below. A backfilled row must stay forever tellable from a
# live-frozen one: it was costed from a DATED `ItemCostListHistory` row
# (`costo_fecha` set), never from the current `ProductoERP.costo` these two
# `congelar()`-side constants mean. Same linkage split as
# `FUENTE_PUBLICACION`/`FUENTE_SKU` above, just for the history path.
FUENTE_BACKFILL_PUBLICACION = "hist_publicacion"
FUENTE_BACKFILL_SKU = "hist_sku"

# A pack/combo/kit HAS NO COST OF ITS OWN. It is not something anyone
# buys, so the ERP will never carry a purchase cost for it, and the zero
# sitting in its cost history is a CONSEQUENCE of that, not a data-entry
# oversight (measured: packs and combos account for 3.470 of the 4.249
# sales the backfill could not cost). Its cost is the sum of its
# components, resolved from `tb_item_association`. Stamped distinctly so a
# reader can always tell a SUMMED cost from a READ one.
FUENTE_BACKFILL_COMBO = "hist_combo"

# Live-path counterpart of `FUENTE_BACKFILL_COMBO` -- a combo costed by
# summing its CURRENT components' `ProductoERP.costo` (never a dated
# history row; the dated path stays exclusive to the backfill per the
# module docstring above).
FUENTE_COMBO = "combo"


def tiene_costo_propio(producto: ProductoERP) -> bool:
    """Whether `producto.costo` is a REAL cost, not a hole in the ERP.

    `erp_sync.sincronizar_erp` reads `coslis_price` with
    `convertir_a_numero(producto_data.get("coslis_price", 0))` -- default
    `0`, never `None`. So a product with no cost row in the ERP (a
    pack/combo/kit is the dominant case: nobody buys a pack, so the ERP
    never carries a purchase cost for it) lands in `productos_erp.costo`
    as `0.0`, NEVER as `NULL`. `producto.costo is None` alone is therefore
    the wrong test on THIS field -- it is only ever true for a row this
    service itself has not synced yet, not for the "no cost" case the sync
    actually produces.

    Same criterion the backfill's `_tiene_precio`
    (`app/scripts/backfill_costo_congelado.py`) already applies to
    `ItemCostListHistory.iclh_price` -- that predicate's own docstring:
    "A NULL or <= 0 `iclh_price` is a HOLE in the ERP, not a product that
    became free." `producto.costo` is a different column on a different
    model, so the two predicates cannot share code, only the rule.
    """
    if producto.costo is None:
        return False
    try:
        return Decimal(str(producto.costo)) > 0
    except InvalidOperation:
        return False


@dataclass(frozen=True)
class _ResolvedCost:
    """Everything needed to freeze ONE item's snapshot, always complete.

    There is no partially-resolved variant on purpose. When the linkage,
    the cost, the IVA rate or the exchange rate cannot be resolved,
    `_resolve_cost` returns `None` for the item as a whole and no row is
    written at all -- "unknown is not zero", and never a half-frozen row
    that reads like a real one."""

    costo_origen: Decimal
    moneda: str
    tipo_cambio: Optional[Decimal]
    tipo_cambio_fecha: Optional[Any]
    costo_unitario_ars: Decimal
    iva_pct: Decimal
    fuente: str
    producto_item_id: int


def _insert_stmt(db: Session, table: Any) -> Any:
    """Same dialect-appropriate `INSERT ... ON CONFLICT` selection as
    `ingestion_service._insert_stmt` -- both PostgreSQL (production) and
    SQLite (`tests/conftest.py`'s in-memory test DB) support
    `on_conflict_do_nothing` with the same call shape."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _productos_por_item(db: Session, items: Sequence[OrderItemOpsDTO]) -> Dict[int, tuple[ProductoERP, str]]:
    """Every item's `ProductoERP`, resolved in THREE queries for the whole
    order instead of up to three PER ITEM.

    This runs inside `upsert_order`, which the reconciliation sweep calls
    over thousands of orders -- "an order has few items" is not the bound
    that matters, few-items x thousands-of-orders is. This module already
    pays that discipline for the existence guard; resolving the product any
    other way would break the same rule two lines below its own comment.

    Linkage per design D6: the MLA (`item_id`) through `PublicacionML` to
    `ProductoERP.item_id`, falling back to `seller_sku` -> `ProductoERP
    .codigo`. The MLA string is NEVER joined against the ERP integer id
    directly. An item that resolves through neither is simply absent from
    the returned map -- an UNKNOWN, not an error.
    """
    mlas = {item.item_id for item in items if item.item_id}
    skus = {item.seller_sku for item in items if item.seller_sku}

    publicaciones: Dict[str, int] = {}
    if mlas:
        publicaciones = {
            row.mla: row.item_id
            for row in db.query(PublicacionML.mla, PublicacionML.item_id).filter(PublicacionML.mla.in_(sorted(mlas)))
        }

    productos_por_erp_id: Dict[int, ProductoERP] = {}
    erp_ids = {erp_id for erp_id in publicaciones.values() if erp_id is not None}
    if erp_ids:
        productos_por_erp_id = {
            producto.item_id: producto
            for producto in db.query(ProductoERP).filter(ProductoERP.item_id.in_(sorted(erp_ids)))
        }

    productos_por_codigo: Dict[str, ProductoERP] = {}
    if skus:
        productos_por_codigo = {
            producto.codigo: producto for producto in db.query(ProductoERP).filter(ProductoERP.codigo.in_(sorted(skus)))
        }

    resueltos: Dict[int, tuple[ProductoERP, str]] = {}
    for idx, item in enumerate(items):
        erp_id = publicaciones.get(item.item_id) if item.item_id else None
        producto = productos_por_erp_id.get(erp_id) if erp_id is not None else None
        if producto is not None:
            resueltos[idx] = (producto, FUENTE_PUBLICACION)
            continue
        if item.seller_sku:
            producto = productos_por_codigo.get(item.seller_sku)
            if producto is not None:
                resueltos[idx] = (producto, FUENTE_SKU)
    return resueltos


def componentes_por_combo(db: Session, erp_ids: Sequence[int]) -> Dict[int, List[Tuple[int, Decimal]]]:
    """`{combo_item_id: [(component_item_id, qty), ...]}` for this batch of
    ERP item ids, in ONE query -- never one per item (same bulk rule
    `_productos_por_item` documents).

    SHARED between the backfill (`app/scripts/backfill_costo_congelado.py`)
    and the live path below -- both need the exact same "what is this
    combo made of" answer, including the same refusal to sum across
    companies. Moved here (rather than duplicated) so the day this bill-of-
    materials rule changes, it changes in ONE place for both callers.

    `tb_item_association` is the ERP's bill of materials: `item_id` is the
    parent, `item_id_1` the component, `iasso_qty` how many of it go in.
    `iasso_qty > 0` is what `prearmado.buscar_combos` already uses to
    decide "this is a combo", and this follows that definition rather than
    inventing a second one."""
    if not erp_ids:
        return {}
    rows = (
        db.query(
            TbItemAssociation.item_id,
            TbItemAssociation.item_id_1,
            TbItemAssociation.iasso_qty,
            TbItemAssociation.comp_id,
        )
        .filter(
            TbItemAssociation.item_id.in_(sorted(set(erp_ids))),
            TbItemAssociation.iasso_qty > 0,
        )
        .all()
    )
    por_combo: Dict[int, List[Tuple[int, Decimal]]] = {}
    empresas_por_combo: Dict[int, set] = {}
    for combo_id, componente_id, qty, comp_id in rows:
        if componente_id is None:
            continue
        por_combo.setdefault(combo_id, []).append((componente_id, Decimal(str(qty))))
        empresas_por_combo.setdefault(combo_id, set()).add(comp_id)

    # `comp_id` is the ERP's COMPANY, and it is part of this table's key.
    # Summing across companies is REFUSED rather than silently attempted:
    # `ProductoERP` carries no company of its own, so there is no way to
    # tell which company's components belong to the combo being costed --
    # a sum over both would be a number that corresponds to neither.
    # Measured: production holds exactly ONE `comp_id` today, so this never
    # fires; it exists so a second company SAYS SO instead of quietly
    # summing both.
    for combo_id, empresas in empresas_por_combo.items():
        if len(empresas) > 1:
            logger.warning(
                "costeo_service.componentes_por_combo: combo item_id=%s has components in %s companies "
                "(comp_id=%s) -- refusing to sum across companies",
                combo_id,
                len(empresas),
                sorted(empresas),
            )
            por_combo.pop(combo_id, None)
    return por_combo


def _resolve_usd_rate(db: Session, usd_rate_cache: Dict[str, Any]) -> Optional[Tuple[Decimal, Any]]:
    """The single `latest_usd_rate_with_date` lookup for this whole
    `congelar()` call, memoized in `usd_rate_cache` -- called from BOTH the
    plain path and the combo path below so a combo with several USD
    components never resolves the rate more than once (design: FX
    resolved once per batch, never per item, never per component)."""
    if "resolved" not in usd_rate_cache:
        # No try/except: `latest_usd_rate_with_date` RETURNS None when
        # there is no usable rate, it does not raise. Catching
        # `MissingExchangeRateError` here suggested a guarantee that is
        # not there, and the `is None` branch below already covers it.
        usd_rate_cache["resolved"] = latest_usd_rate_with_date(db)
    rate_result = usd_rate_cache["resolved"]
    if rate_result is None:
        return None
    rate_value, rate_date = rate_result
    return Decimal(str(rate_value)), rate_date


def _convertir_a_ars(
    db: Session,
    costo_origen: Decimal,
    moneda: str,
    producto_item_id: int,
    usd_rate_cache: Dict[str, Any],
) -> Optional[Tuple[Decimal, Optional[Decimal], Optional[Any]]]:
    """`(costo_unitario_ars, tipo_cambio, tipo_cambio_fecha)` or `None` when
    the currency is USD with no usable rate, or is neither ARS nor USD.
    Shared by the plain single-product path and the combo-sum path so a
    component and a stand-alone product are never converted by two
    different rules."""
    if moneda == "USD":
        rate = _resolve_usd_rate(db, usd_rate_cache)
        if rate is None:
            # No usable TipoCambio row: a USD cost cannot be converted, so
            # the whole snapshot is unknown -- never send the unconverted
            # USD figure through as if it were ARS.
            return None
        tipo_cambio, tipo_cambio_fecha = rate
        return costo_origen * tipo_cambio, tipo_cambio, tipo_cambio_fecha
    if moneda != "ARS":
        logger.warning(
            "costeo_service: unrecognized moneda_costo=%r for producto_item_id=%s",
            moneda,
            producto_item_id,
        )
        return None
    return costo_origen, None, None


def _moneda_de(producto: ProductoERP) -> str:
    moneda = (producto.moneda_costo.value if producto.moneda_costo is not None else "ARS") or "ARS"
    return str(moneda).upper()


def _resolver_combo_vivo(
    db: Session,
    componentes: Sequence[Tuple[int, Decimal]],
    productos_componentes: Dict[int, ProductoERP],
    usd_rate_cache: Dict[str, Any],
) -> Optional[Tuple[Decimal, Optional[Decimal], Optional[Any]]]:
    """A pack/combo/kit's cost, live: the sum of its CURRENT components'
    `ProductoERP.costo`, each converted to ARS, times how many go in.

    ALL OR NOTHING, same discipline the backfill's `_resolver_combo`
    documents: one component that does not resolve to a `ProductoERP`, or
    whose own `costo` is unknown (per `tiene_costo_propio` -- `NULL` or
    `<= 0`, the sync never distinguishes "no cost row" from `0.0`), or
    whose currency cannot be converted, sinks the WHOLE combo -- never a
    partial sum.

    NO RECURSION: a component that is itself a combo (no `costo` of its
    own) is NOT resolved by summing ITS components -- it is treated the
    same as any other component with an unknown cost, and the whole combo
    fails closed. The backfill's `_resolver_combo` has the identical gap
    (it looks up a component's dated history row directly, never recurses
    into `_componentes_por_combo` for it); this mirrors that rather than
    silently doing more than the backfill's already-shipped behaviour."""
    total = Decimal("0")
    tipo_cambio: Optional[Decimal] = None
    tipo_cambio_fecha = None

    for componente_id, qty in componentes:
        componente = productos_componentes.get(componente_id)
        if componente is None or not tiene_costo_propio(componente):
            return None
        try:
            costo_componente = Decimal(str(componente.costo))
        except InvalidOperation:
            return None
        moneda_componente = _moneda_de(componente)
        convertido = _convertir_a_ars(db, costo_componente, moneda_componente, componente.item_id, usd_rate_cache)
        if convertido is None:
            return None
        valor_ars, tc, tc_fecha = convertido
        total += valor_ars * qty
        if tc is not None:
            tipo_cambio = tc
            tipo_cambio_fecha = tc_fecha

    return total, tipo_cambio, tipo_cambio_fecha


def _resolve_cost(
    db: Session,
    resuelto: Optional[tuple[ProductoERP, str]],
    usd_rate_cache: Dict[str, Any],
    componentes_por_combo: Optional[Dict[int, List[Tuple[int, Decimal]]]] = None,
    productos_componentes: Optional[Dict[int, ProductoERP]] = None,
) -> Optional[_ResolvedCost]:
    """Resolves one item's cost snapshot, or `None` on any unknown step:
    no linked product, missing `costo` (and no costable combo composition),
    missing `iva`, or (for a USD-costed product/component) no exchange rate
    available. `usd_rate_cache` is populated at most once per `congelar()`
    call (design: FX resolved once per batch, never per item)."""
    if resuelto is None:
        return None
    producto, fuente = resuelto

    if producto.iva is None:
        return None
    try:
        iva_pct = Decimal(str(producto.iva))
    except InvalidOperation:
        logger.warning("costeo_service: unparseable iva for producto_item_id=%s", producto.item_id)
        return None

    if tiene_costo_propio(producto):
        # The product's OWN cost comes first, even if it also happens to
        # have `tb_item_association` rows -- a product the ERP actually
        # prices is costed with that figure, never with a derived sum
        # (same order-of-preference the backfill's `_resolve_backfill_cost`
        # documents).
        try:
            costo_origen = Decimal(str(producto.costo))
        except InvalidOperation:
            logger.warning("costeo_service: unparseable costo for producto_item_id=%s", producto.item_id)
            return None
        moneda = _moneda_de(producto)
        convertido = _convertir_a_ars(db, costo_origen, moneda, producto.item_id, usd_rate_cache)
        if convertido is None:
            return None
        costo_unitario_ars, tipo_cambio, tipo_cambio_fecha = convertido
        return _ResolvedCost(
            costo_origen=costo_origen,
            moneda=moneda,
            tipo_cambio=tipo_cambio,
            tipo_cambio_fecha=tipo_cambio_fecha,
            costo_unitario_ars=costo_unitario_ars,
            iva_pct=iva_pct,
            fuente=fuente,
            producto_item_id=producto.item_id,
        )

    # No cost of its own -- the only remaining honest answer is "unknown",
    # unless the ERP knows this item's bill of materials (design item: a
    # pack/combo/kit has no purchase cost because nobody buys a pack).
    componentes = (componentes_por_combo or {}).get(producto.item_id)
    if not componentes:
        return None

    resuelto_combo = _resolver_combo_vivo(db, componentes, productos_componentes or {}, usd_rate_cache)
    if resuelto_combo is None:
        return None
    total_ars, tipo_cambio, tipo_cambio_fecha = resuelto_combo
    if total_ars <= 0:
        return None

    return _ResolvedCost(
        # Already summed IN ARS: a combo can mix an ARS component with a
        # USD one, so there is no single source currency to report --
        # same reasoning the backfill's `_resolver_combo` documents.
        costo_origen=total_ars,
        moneda="ARS",
        tipo_cambio=tipo_cambio,
        tipo_cambio_fecha=tipo_cambio_fecha,
        costo_unitario_ars=total_ars,
        iva_pct=iva_pct,
        fuente=FUENTE_COMBO,
        producto_item_id=producto.item_id,
    )


def congelar(db: Session, order_id: int, items: Sequence[OrderItemOpsDTO]) -> None:
    """Freezes a cost/IVA/exchange-rate snapshot for every item in `items`
    that resolves completely (design D6/D7). Called once per order, AFTER
    `_upsert_item_row` for all of the order's items.

    KNOWN GAP, stated rather than left implicit: this only runs when
    `_upsert_order_row` applied, so an order that froze NOTHING because the
    linkage did not resolve is retried only if ML updates that order again.
    If ML never does, the sale stays uncosted forever. Closing that needs a
    backfill pass over orders with items but no frozen rows -- it is NOT in
    this slice, and it must not be forgotten.

    Runs BEFORE `_delete_stale_items`, and a frozen row deliberately
    OUTLIVES the item it describes: if an item later disappears from the
    order (a partial cancellation), its cost snapshot stays. That is the
    point of freezing -- what the sale cost us when it happened does not
    stop being true because the order changed afterwards. So do NOT assume
    every row here has a live `MlOrderItemOps` behind it.

    INSERT-only: `ON CONFLICT DO NOTHING` on `(order_id, item_id,
    variation_id)` means an item that already has a frozen row is a
    structural no-op here, regardless of what the ERP or the exchange rate
    look like today (design D5). Does NOT commit -- the caller owns the
    transaction boundary, same as `upsert_order`.
    """
    usd_rate_cache: Dict[str, Any] = {}
    productos_por_indice = _productos_por_item(db, items)

    # Combo composition for the whole batch, in ONE query -- only for
    # products that have no cost of their own, since a product the ERP
    # actually prices is never treated as a combo (see `_resolve_cost`).
    # Component products are fetched in a SECOND bulk query, same
    # discipline `run_backfill` follows: never one round-trip per combo.
    erp_ids_sin_costo = {
        producto.item_id for producto, _ in productos_por_indice.values() if not tiene_costo_propio(producto)
    }
    combos = componentes_por_combo(db, erp_ids_sin_costo)
    componente_ids = {componente_id for componentes in combos.values() for componente_id, _ in componentes}
    productos_componentes: Dict[int, ProductoERP] = {}
    if componente_ids:
        productos_componentes = {
            producto.item_id: producto
            for producto in db.query(ProductoERP).filter(ProductoERP.item_id.in_(sorted(componente_ids)))
        }

    # Existence guard, dialect-independent, resolved in ONE query before the
    # loop rather than one per item.
    #
    # It exists because SQLite's unique index does NOT honour
    # `postgresql_nulls_not_distinct` -- that is a Postgres-only dialect
    # kwarg, and SQLite keeps treating two NULL `variation_id` rows as
    # distinct (measured, not assumed). So `ON CONFLICT DO NOTHING` alone
    # would let a re-ingestion insert a SECOND row for the no-variation
    # case, which is the COMMON one, under the test DB only: the invariant
    # would read as proven while the proof ran on the one engine that
    # cannot express it. `ON CONFLICT DO NOTHING` stays below as the
    # concurrency-safe backstop on PostgreSQL.
    ya_congelados = {
        (row.item_id, row.variation_id)
        for row in db.query(MlOrderItemCosto.item_id, MlOrderItemCosto.variation_id).filter(
            MlOrderItemCosto.order_id == order_id
        )
    }

    for indice, item in enumerate(items):
        if (item.item_id, item.variation_id) in ya_congelados:
            continue

        if item.unit_price is None:
            # `precio_unitario` is a frozen fiscal figure (design D10 feeds
            # off it later) -- an item with no price is unknown, not zero.
            continue

        resolved = _resolve_cost(db, productos_por_indice.get(indice), usd_rate_cache, combos, productos_componentes)
        if resolved is None:
            continue

        try:
            precio_unitario = Decimal(str(item.unit_price))
        except InvalidOperation:
            continue

        values: Dict[str, Any] = {
            "order_id": order_id,
            "item_id": item.item_id,
            "variation_id": item.variation_id,
            "costo_origen": resolved.costo_origen,
            "moneda": resolved.moneda,
            "tipo_cambio": resolved.tipo_cambio,
            "tipo_cambio_fecha": resolved.tipo_cambio_fecha,
            "costo_unitario_ars": resolved.costo_unitario_ars,
            "iva_pct": resolved.iva_pct,
            "precio_unitario": precio_unitario,
            "fuente": resolved.fuente,
            "producto_item_id": resolved.producto_item_id,
        }
        stmt = _insert_stmt(db, MlOrderItemCosto.__table__).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["order_id", "item_id", "variation_id"],
        )
        db.execute(stmt)
