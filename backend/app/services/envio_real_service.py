"""
envio_real_service — resolves the real ML shipping cost for a product.

Replaces static ProductoERP.envio with MAX(list_cost) from ml_seller_shipping_costs
in the mlwebhook DB. All consumers that need a shipping cost for pricing or display
MUST call resolver_costo_envio (single) or resolver_costos_envio_batch (bulk).

Design decisions (ADR):
  1. New module isolates cross-DB I/O from the pure pricing formula.
  2. MAX computed in Python because the mla→item_id mapping lives in the main DB;
     cross-DB GROUP BY is not possible.
  3. Batch dict is keyed by item_id for O(1) lookup in listing loops.
  4. list_cost is stored WITH IVA in ml_seller_shipping_costs → returned AS-IS.
     calcular_limpio performs the /1.21 division; this module must NOT do it.
  5. Broad try/except on every cross-DB call → graceful ERP fallback, never raises.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_mlwebhook_engine
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal cross-DB helper
# ---------------------------------------------------------------------------


def _fetch_list_cost_by_mla(mla_ids: list[str]) -> dict[str, float]:
    """
    Query ml_seller_shipping_costs in the mlwebhook DB for the given MLA IDs.

    Returns {mla_id: list_cost} for rows where list_cost > 0 and currency_id = 'ARS'.
    Returns an empty dict on any error (DB unreachable, table missing, etc.).

    list_cost is stored WITH IVA — returned as-is; caller decides what to do with it.
    """
    result: dict[str, float] = {}
    if not mla_ids:
        return result

    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT mla_id, list_cost
                    FROM ml_seller_shipping_costs
                    WHERE mla_id = ANY(:ids)
                      AND list_cost IS NOT NULL
                      AND list_cost > 0
                      AND currency_id = 'ARS'
                    """
                ),
                {"ids": mla_ids},
            ).fetchall()
        for row in rows:
            result[row.mla_id] = float(row.list_cost)
    except Exception as exc:
        logger.warning("No se pudo consultar ml_seller_shipping_costs: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Single-product resolver
# ---------------------------------------------------------------------------


def resolver_costo_envio(
    db: Session,
    producto: ProductoERP,
    *,
    mlas_activas: Optional[list[PublicacionML]] = None,
) -> float:
    """
    Return the resolved shipping cost (ARS, with IVA) for a single product.

    Resolution strategy:
      1. Load active PublicacionML rows for the product (uses mlas_activas if provided).
      2. Query ml_seller_shipping_costs for those MLA IDs via _fetch_list_cost_by_mla.
      3. Compute MAX(list_cost) across all results.
      4. If MAX is available, return it.
      5. Otherwise return ProductoERP.envio (ERP fallback).

    This function NEVER raises. All cross-DB exceptions are caught internally.

    Args:
        db: Main application DB session.
        producto: ProductoERP instance (used for item_id and fallback envio).
        mlas_activas: Pre-loaded list of PublicacionML rows (avoids repeated query).
                      If None, they are loaded from the DB.

    Returns:
        Shipping cost in ARS with IVA, as a float.
    """
    # Step 1: resolve active MLAs
    if mlas_activas is None:
        pubs: list[PublicacionML] = db.query(PublicacionML).filter(PublicacionML.item_id == producto.item_id).all()
    else:
        pubs = mlas_activas

    active_mla_ids = [p.mla for p in pubs if p.activo]

    if not active_mla_ids:
        return float(producto.envio or 0.0)

    # Step 2: fetch shipping costs from mlwebhook DB
    costs = _fetch_list_cost_by_mla(active_mla_ids)

    if not costs:
        return float(producto.envio or 0.0)

    # Step 3: MAX in Python (cross-DB GROUP BY is not possible)
    return max(costs.values())


# ---------------------------------------------------------------------------
# Batch resolver
# ---------------------------------------------------------------------------


def resolver_costos_envio_batch(
    db: Session,
    item_ids: list[int],
    *,
    pubs_by_item: Optional[dict[int, list[PublicacionML]]] = None,
) -> dict[int, float]:
    """
    Return resolved shipping costs for a batch of products.

    Returns a dict keyed by item_id. Items for which no real cost is found
    (no active MLAs, no list_cost, or DB unreachable) are ABSENT from the result.
    Callers should use .get(item_id) and fall back to ProductoERP.envio when None.

    This function NEVER raises. All cross-DB exceptions are caught; on any failure
    the entire batch returns {} so callers fall back to ERP envio for all items.

    Args:
        db: Main application DB session.
        item_ids: List of item IDs to resolve.
        pubs_by_item: Pre-computed {item_id: [PublicacionML, ...]} mapping.
                      When provided, no main-DB query is issued.

    Returns:
        {item_id: max_list_cost} for items that have a resolvable real cost.
    """
    if not item_ids:
        return {}

    # Step 1: build active MLA sets per item
    if pubs_by_item is None:
        all_pubs: list[PublicacionML] = db.query(PublicacionML).filter(PublicacionML.item_id.in_(item_ids)).all()
        pubs_by_item = {}
        for pub in all_pubs:
            pubs_by_item.setdefault(pub.item_id, []).append(pub)

    # Collect all active MLA IDs (deduped) and remember item→mla mapping
    item_to_active_mlas: dict[int, list[str]] = {}
    all_active_mlas: list[str] = []

    for item_id in item_ids:
        pubs = pubs_by_item.get(item_id, [])
        active_ids = [p.mla for p in pubs if p.activo]
        if active_ids:
            item_to_active_mlas[item_id] = active_ids
            all_active_mlas.extend(active_ids)

    if not all_active_mlas:
        return {}

    # Step 2: one cross-DB query for all MLAs
    try:
        costs = _fetch_list_cost_by_mla(list(set(all_active_mlas)))
    except Exception as exc:
        # _fetch already catches internally, but guard here for safety
        logger.warning("resolver_costos_envio_batch: error inesperado: %s", exc)
        return {}

    if not costs:
        return {}

    # Step 3: compute MAX per item
    result: dict[int, float] = {}
    for item_id, mla_ids in item_to_active_mlas.items():
        item_costs = [costs[mla] for mla in mla_ids if mla in costs]
        if item_costs:
            result[item_id] = max(item_costs)

    return result
