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

Absence at any step, or a NULL `costo`/`iva` once a product IS found, means
UNKNOWN -- no row is written for that item. `Decimal(str(...))` conversion
happens HERE, at the first read of `ProductoERP.costo`/`.iva` (both `Float`
columns) -- never later in the chain (money-path Decimal discipline).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Sequence

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO
from app.services.tn_publish_core.resolve import (
    latest_usd_rate_with_date,
)

logger = logging.getLogger(__name__)


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


def _productos_por_item(db: Session, items: Sequence[OrderItemOpsDTO]) -> Dict[int, ProductoERP]:
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

    resueltos: Dict[int, ProductoERP] = {}
    for idx, item in enumerate(items):
        erp_id = publicaciones.get(item.item_id) if item.item_id else None
        producto = productos_por_erp_id.get(erp_id) if erp_id is not None else None
        if producto is None and item.seller_sku:
            producto = productos_por_codigo.get(item.seller_sku)
        if producto is not None:
            resueltos[idx] = producto
    return resueltos


def _resolve_cost(
    db: Session,
    producto: Optional[ProductoERP],
    usd_rate_cache: Dict[str, Any],
) -> Optional[_ResolvedCost]:
    """Resolves one item's cost snapshot, or `None` on any unknown step:
    no linked product, missing `costo`, missing `iva`, or (for a USD-costed
    product) no exchange rate available. `usd_rate_cache` is populated at
    most once per `congelar()` call (design: FX resolved once per batch,
    never per item)."""
    if producto is None:
        return None

    if producto.costo is None:
        return None
    if producto.iva is None:
        return None

    try:
        costo_origen = Decimal(str(producto.costo))
        iva_pct = Decimal(str(producto.iva))
    except InvalidOperation:
        logger.warning("costeo_service: unparseable costo/iva for producto_item_id=%s", producto.item_id)
        return None

    moneda = (producto.moneda_costo.value if producto.moneda_costo is not None else "ARS") or "ARS"
    moneda = str(moneda).upper()

    tipo_cambio: Optional[Decimal] = None
    tipo_cambio_fecha = None
    costo_unitario_ars = costo_origen

    if moneda == "USD":
        if "resolved" not in usd_rate_cache:
            # No try/except: `latest_usd_rate_with_date` RETURNS None when
            # there is no usable rate, it does not raise. Catching
            # `MissingExchangeRateError` here suggested a guarantee that is
            # not there, and the `is None` branch below already covers it.
            usd_rate_cache["resolved"] = latest_usd_rate_with_date(db)
        rate_result = usd_rate_cache["resolved"]
        if rate_result is None:
            # No usable TipoCambio row: a USD cost cannot be converted, so
            # the whole snapshot is unknown for this item -- never send the
            # unconverted USD figure through as if it were ARS.
            return None
        rate_value, rate_date = rate_result
        tipo_cambio = Decimal(str(rate_value))
        tipo_cambio_fecha = rate_date
        costo_unitario_ars = costo_origen * tipo_cambio
    elif moneda != "ARS":
        logger.warning(
            "costeo_service: unrecognized moneda_costo=%r for producto_item_id=%s",
            moneda,
            producto.item_id,
        )
        return None

    return _ResolvedCost(
        costo_origen=costo_origen,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        tipo_cambio_fecha=tipo_cambio_fecha,
        costo_unitario_ars=costo_unitario_ars,
        iva_pct=iva_pct,
        fuente="erp",
        producto_item_id=producto.item_id,
    )


def congelar(db: Session, order_id: int, items: Sequence[OrderItemOpsDTO]) -> None:
    """Freezes a cost/IVA/exchange-rate snapshot for every item in `items`
    that resolves completely (design D6/D7). Called once per order, AFTER
    `_upsert_item_row` for all of the order's items.

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

        resolved = _resolve_cost(db, productos_por_indice.get(indice), usd_rate_cache)
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
