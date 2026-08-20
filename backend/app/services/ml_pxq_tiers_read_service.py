"""Cross-DB read service for MercadoLibre PxQ wholesale tiers (base
mlwebhook, READ-ONLY).

ml-webhook sweeps the live publications and persists their quantity/amount
tiers into its own DB; pricing-app only READS them here. Same engine and same
error contract as `ml_promotions_service` (`get_mlwebhook_engine`), never the
pricing session.

Why a sibling module instead of `ml_promotions_service`: promotions and PxQ
tiers are unrelated domains that merely share a transport, and the `ml_pxq*`
filename prefix keeps this file inside the AST base-price boundary scan
(`tests/unit/test_pxq_base_price_boundary.py`) at no extra cost — a PxQ reader
living under the promotions name would silently fall outside it.

Schema (base mlwebhook):

    ml_pxq_price_tiers
        mla          TEXT
        quantity     INTEGER      -- PK(mla, quantity)
        amount       NUMERIC(18,2)
        currency_id  TEXT
        price_id     TEXT
        updated_at   TIMESTAMPTZ

Scale note: 46 publications carry tiers out of 5717 active (0.80%, measured in
prod). The whole set fits in memory — no paging, no batching beyond the single
query each reader already issues.

This module must NEVER import `ProductoPricing`: PxQ tiers are quantity prices
layered on top of the base price and never touch that table (design D3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set

from sqlalchemy import text

from app.core.database import get_mlwebhook_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PxqTier:
    """One wholesale tier: buy `quantity` or more, pay `amount` per unit."""

    quantity: int
    amount: float


def fetch_mlas_with_pxq_tiers(mla_ids: Optional[Sequence[str]] = None) -> Set[str]:
    """Read the set of MLAs that have at least one PxQ wholesale tier.

    Backs the "Con precios mayoristas" filter at BOTH levels:

    * PRODUCT level (Productos listing): called without `mla_ids`, folded
      into the listing query by `_resolve_and_fold_mlas`, which owns the
      empty-set fail-closed guard and the 503 mapping.
    * PUBLICATION level (`matches_filter` on the detail/tree endpoints):
      called WITH this product's own `mla_ids`, so the filter also hides the
      publications of a matching product that carry no tiers. Mirrors
      `fetch_mlas_with_active_promo_type`'s `mla_ids` parameter — same shape,
      same reason: never pull the account universe to answer about one
      product.

    Args:
        mla_ids: optional scope. `None` reads the whole universe; a non-empty
            list bounds the query to those MLAs. An EMPTY list short-circuits
            to the empty set without querying: a product with no publications
            matches nothing (this is "nothing matches", never "filter off").

    Returns:
        Set of mla (str). Empty if no publication in scope has tiers.

    Raises:
        RuntimeError: if ML_WEBHOOK_DB_URL is not configured.
        SQLAlchemyError: on a DB/connection fault.

        Both propagate on purpose, and the two levels translate them
        DIFFERENTLY: the listing maps them to 503 (fail-closed — returning
        unfiltered rows would lie), while the per-MLA callers swallow them
        into an absent `matches_filter` (fail-open — an infrastructure blip
        must not hide a publication). Swallowing them HERE would collapse
        both stories into the wrong one.
    """
    if mla_ids is not None and not mla_ids:
        return set()

    scope_clause = "WHERE mla = ANY(:mla_ids)" if mla_ids else ""
    params = {"mla_ids": list(mla_ids)} if mla_ids else {}

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT DISTINCT mla
                FROM ml_pxq_price_tiers
                {scope_clause}
            """),
            params,
        ).fetchall()

    result = {row[0] for row in rows}
    logger.info("ml_pxq_price_tiers: %d mlas with wholesale tiers", len(result))
    return result


def fetch_pxq_tiers_by_mla(mla_ids: Sequence[str]) -> Dict[str, List[PxqTier]]:
    """Read the PxQ tiers of the given MLAs, grouped by mla and ordered by
    quantity ascending.

    Backs the listing's quick-view chip ("3 tramos · desde $37.800"). ONE
    batched query scoped to the MLAs of the CURRENT PAGE — never one query per
    product, and never the whole universe.

    Args:
        mla_ids: MLAs to look up. Empty issues no query at all (mirrors
            `fetch_mlas_with_active_promo_type`'s guard).

    Returns:
        {mla: [PxqTier, ...]} for the MLAs that have tiers. MLAs without tiers
        are simply absent from the dict.

    Raises:
        RuntimeError / SQLAlchemyError: same contract as above. The quick view
        is FAIL-OPEN, but that is the caller's decision to make — this reader
        surfaces the fault rather than faking an empty read.
    """
    if not mla_ids:
        return {}

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT mla, quantity, amount
                FROM ml_pxq_price_tiers
                WHERE mla = ANY(:mla_ids)
                ORDER BY mla, quantity
            """),
            {"mla_ids": list(mla_ids)},
        ).fetchall()

    result: Dict[str, List[PxqTier]] = {}
    for mla, quantity, amount in rows:
        result.setdefault(mla, []).append(PxqTier(quantity=int(quantity), amount=float(amount)))

    # Re-sorted in Python as well as in SQL: the ORDER BY is the cheap path,
    # this is the one the chip's "desde" price actually depends on.
    for tiers in result.values():
        tiers.sort(key=lambda tier: tier.quantity)

    logger.info("ml_pxq_price_tiers: tiers read for %d of %d mlas", len(result), len(mla_ids))
    return result
