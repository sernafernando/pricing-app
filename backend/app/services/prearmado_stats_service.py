"""Prearmado stats service — batch exact/upgrade counts and armadas list.

Architecture
------------
Two public entry points:

1. ``compute_batch_stats(item_ids, comp_id, db, redis, force_refresh)``
   Returns counts of armado-state prearmados that cover each requested item_id.
   Two SQL queries (no N+1), Redis MGET/SETEX caching, graceful when Redis is down.
   This is an async function because the Redis client (``redis.asyncio.Redis``)
   requires ``await``.

2. ``get_armadas_list(comp_id, db, search, page, page_size)``
   Returns paginated list of armado prearmados enriched with covers[].
   Two SQL queries (prearmados + all combo items), classification in Python.
   Synchronous — no cache layer.

Classification (ADR-1)
----------------------
Python-side, not SQL-CASE. Hierarchy: None < home < pro.
  - exact   → same base + memoria + disco + windows
  - upgrade → same base + memoria + disco, but prearmado.windows > pedido.windows
  - none    → prearmado cannot satisfy the item requirement
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.prearmado import Prearmado
from app.models.tb_item import TBItem
from app.services.prearmado_ean_parser import ParsedEan, parse_combo_ean

logger = logging.getLogger(__name__)

# Windows ordinal for upgrade comparison.  None = no windows, 0; home = 1; pro = 2.
_WIN_RANK: dict[Optional[str], int] = {None: 0, "home": 1, "pro": 2}

CacheStatus = Literal["hit", "miss", "partial"]


def classify(req_windows: Optional[str], have_windows: Optional[str]) -> Literal["exact", "upgrade", "none"]:
    """Classify whether a prearmado covers a requested item (windows dimension only).

    Precondition: base, memoria, and disco match have already been verified by the
    caller. This function only resolves the windows dimension.

    Parameters
    ----------
    req_windows:
        Windows requirement from the pedido item. ``None`` = no windows needed.
    have_windows:
        Windows capability of the prearmado. ``None`` = no windows included.

    Returns
    -------
    "exact"   : prearmado.windows == item.windows
    "upgrade" : prearmado.windows > item.windows (covers with surplus)
    "none"    : prearmado.windows < item.windows (insufficient coverage)
    """
    if req_windows == have_windows:
        return "exact"
    if _WIN_RANK[have_windows] > _WIN_RANK[req_windows]:
        return "upgrade"
    return "none"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IndexKey = tuple[str, Optional[str], Optional[str]]  # (ean_base, memoria, disco)


def _build_prearmadas_index(
    prearmadas: list[Prearmado],
) -> dict[_IndexKey, list[ParsedEan]]:
    """Build an in-memory index of prearmadas keyed by (ean_base, memoria, disco).

    Prearmadas whose ``combo_item_code`` cannot be parsed are skipped with a
    WARNING log — they contribute 0 to all item stats.

    Parameters
    ----------
    prearmadas:
        List of Prearmado ORM objects with ``estado='armado'``.

    Returns
    -------
    dict mapping (ean_base, memoria, disco) → list of ParsedEan objects.
    """
    index: dict[_IndexKey, list[ParsedEan]] = {}
    for p in prearmadas:
        parsed = parse_combo_ean(p.combo_item_code)
        if parsed is None:
            logger.warning(
                "Prearmado id=%s combo_item_code=%r could not be parsed — skipped from stats index",
                p.id,
                p.combo_item_code,
            )
            continue
        key: _IndexKey = (parsed.ean_base, parsed.memoria, parsed.disco)
        index.setdefault(key, []).append(parsed)
    return index


def _count_coverage(
    item_parsed: ParsedEan,
    index: dict[_IndexKey, list[ParsedEan]],
) -> dict[str, int]:
    """Count exact and upgrade prearmados for a parsed item code."""
    key: _IndexKey = (item_parsed.ean_base, item_parsed.memoria, item_parsed.disco)
    candidates = index.get(key, [])
    exact = 0
    upgrade = 0
    for candidate in candidates:
        result = classify(item_parsed.windows, candidate.windows)
        if result == "exact":
            exact += 1
        elif result == "upgrade":
            upgrade += 1
    return {"exact": exact, "upgrade": upgrade}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_batch_stats(
    item_ids: list[int],
    comp_id: int,
    db: Session,
    redis: Any,
    *,
    force_refresh: bool = False,
) -> tuple[dict[str, dict[str, int]], CacheStatus]:
    """Compute exact/upgrade counts for a batch of item_ids.

    Two SQL queries total (regardless of batch size).  Uses ``await`` on the
    async Redis client (``redis.asyncio.Redis``).  Graceful degradation when
    Redis is ``None`` (down or not configured): computes from DB every call
    and reports ``cache_status="miss"`` (transparent to clients).

    Parameters
    ----------
    item_ids:
        List of item_ids to compute stats for (may include unknowns/non-combos).
    comp_id:
        Tenant identifier — all queries are scoped to this comp_id.
    db:
        SQLAlchemy session.
    redis:
        Async Redis client (``redis.asyncio.Redis``) from ``app.state.redis``,
        or ``None`` if Redis is down / not configured.
    force_refresh:
        When True, skip cache read and recompute from DB; still updates cache.

    Returns
    -------
    (stats_dict, cache_status)
    stats_dict : dict[str(item_id), {"exact": int, "upgrade": int}]
    cache_status : "hit" | "miss" | "partial"
    """
    if not item_ids:
        return {}, "hit"

    if redis is None:
        logger.info("Redis unavailable — computing prearmadas stats without cache (comp_id=%s)", comp_id)

    # Build Redis keys
    def _cache_key(item_id: int) -> str:
        return f"prearmadas:stats:v1:{comp_id}:{item_id}"

    keys = [_cache_key(iid) for iid in item_ids]

    # ----- Cache read -----
    cached_map: dict[int, dict[str, int]] = {}
    miss_ids: list[int] = list(item_ids)  # assume all miss initially

    if redis is not None and not force_refresh:
        try:
            raw_values = await redis.mget(*keys)
            miss_ids = []
            for iid, raw in zip(item_ids, raw_values):
                if raw is not None:
                    try:
                        cached_map[iid] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        miss_ids.append(iid)
                else:
                    miss_ids.append(iid)
        except Exception as exc:
            logger.warning("Redis MGET failed — bypassing cache for comp_id=%s: %s", comp_id, exc)
            miss_ids = list(item_ids)
            cached_map = {}

    # ----- Compute misses from DB -----
    computed_map: dict[int, dict[str, int]] = {}

    if miss_ids:
        # Query 1: item codes for the requested ids
        items_rows = (
            db.query(TBItem.item_id, TBItem.item_code)
            .filter(TBItem.comp_id == comp_id, TBItem.item_id.in_(miss_ids))
            .all()
        )
        code_map: dict[int, str] = {row.item_id: row.item_code for row in items_rows}

        # Query 2: all armado prearmadas for this comp (hits the partial index)
        prearmadas = (
            db.query(Prearmado)
            .filter(
                Prearmado.comp_id == comp_id,
                Prearmado.estado == "armado",
                Prearmado.combo_item_code.like("%-%"),
            )
            .all()
        )

        if len(prearmadas) > settings.PREARMADAS_STATS_VOLUME_WARN:
            logger.warning(
                "Prearmadas volume (%s) exceeds warn threshold %s for comp_id=%s",
                len(prearmadas),
                settings.PREARMADAS_STATS_VOLUME_WARN,
                comp_id,
            )

        # Build index once (not per item)
        index = _build_prearmadas_index(prearmadas)

        for iid in miss_ids:
            item_code = code_map.get(iid)
            if item_code is None:
                computed_map[iid] = {"exact": 0, "upgrade": 0}
                continue
            item_parsed = parse_combo_ean(item_code)
            if item_parsed is None:
                # Non-combo item (no '-') or unparseable
                computed_map[iid] = {"exact": 0, "upgrade": 0}
                continue
            computed_map[iid] = _count_coverage(item_parsed, index)

    # ----- Cache write -----
    if redis is not None and computed_map:
        ttl = settings.PREARMADAS_STATS_CACHE_TTL_SECONDS
        for iid, counts in computed_map.items():
            try:
                await redis.setex(_cache_key(iid), ttl, json.dumps(counts))
            except Exception as exc:
                logger.warning("Redis SETEX failed for item_id=%s: %s", iid, exc)

    # ----- Merge and determine cache status -----
    stats: dict[str, dict[str, int]] = {}
    for iid in item_ids:
        if iid in cached_map:
            stats[str(iid)] = cached_map[iid]
        else:
            stats[str(iid)] = computed_map.get(iid, {"exact": 0, "upgrade": 0})

    if redis is None:
        # Transparent to clients: report "miss" so the spec contract stays clean.
        cache_status: CacheStatus = "miss"
    elif not cached_map:
        cache_status = "miss"
    elif not computed_map:
        cache_status = "hit"
    else:
        cache_status = "partial"

    return stats, cache_status


def get_armadas_list(
    comp_id: int,
    db: Session,
    *,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Retrieve paginated armado prearmados enriched with covers[].

    Two SQL queries total per request (no N+1).

    Parameters
    ----------
    comp_id:
        Tenant identifier.
    db:
        SQLAlchemy session.
    search:
        Optional case-insensitive substring matched against either
        ``combo_item_code`` or ``combo_item_desc``. Lets sellers filter by SKU,
        brand, or any word in the model description.
    page:
        1-based page number.
    page_size:
        Items per page.

    Returns
    -------
    (items, total)
    items : list of dicts matching the ArmadasListResponse schema.
    total : total count before pagination.
    """
    # Query A: paginated prearmados
    query = db.query(Prearmado).filter(
        Prearmado.comp_id == comp_id,
        Prearmado.estado == "armado",
        Prearmado.combo_item_code.like("%-%"),
    )

    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Prearmado.combo_item_code.ilike(like),
                Prearmado.combo_item_desc.ilike(like),
            )
        )

    total: int = query.count()

    offset = (page - 1) * page_size
    prearmadas = query.order_by(Prearmado.combo_item_code, Prearmado.id).offset(offset).limit(page_size).all()

    # Query B: all combo items for this comp (preloaded once)
    combo_items = (
        db.query(TBItem.item_id, TBItem.item_code, TBItem.item_desc)
        .filter(TBItem.comp_id == comp_id, TBItem.item_code.like("%-%"))
        .all()
    )

    if len(combo_items) > settings.PREARMADAS_STATS_VOLUME_WARN:
        logger.warning(
            "Query B returned %s combo items for comp_id=%s — consider scoped query fallback (design §1.2)",
            len(combo_items),
            comp_id,
        )

    # Build ean_base → list of items map
    items_by_base: dict[str, list[dict[str, Any]]] = {}
    for row in combo_items:
        parsed = parse_combo_ean(row.item_code)
        if parsed is None:
            continue
        items_by_base.setdefault(parsed.ean_base, []).append(
            {
                "item_id": row.item_id,
                "item_code": row.item_code,
                "item_desc": row.item_desc,
                "parsed": parsed,
            }
        )

    # Build response items
    result: list[dict[str, Any]] = []
    for p in prearmadas:
        p_parsed = parse_combo_ean(p.combo_item_code)
        if p_parsed is None:
            logger.warning(
                "Prearmado id=%s combo_item_code=%r could not be parsed — covers will be empty",
                p.id,
                p.combo_item_code,
            )
            p_parsed_dict: dict[str, Any] = {"ean_base": None, "memoria": None, "disco": None, "windows": None}
            covers: list[dict[str, Any]] = []
        else:
            p_parsed_dict = {
                "ean_base": p_parsed.ean_base,
                "memoria": p_parsed.memoria,
                "disco": p_parsed.disco,
                "windows": p_parsed.windows,
            }
            # Compute covers for items in the same ean_base bucket
            candidates_in_base = items_by_base.get(p_parsed.ean_base, [])
            covers = []
            for item_info in candidates_in_base:
                item_parsed: ParsedEan = item_info["parsed"]
                # Check base + memoria + disco match (windows classified separately)
                if item_parsed.memoria != p_parsed.memoria:
                    continue
                if item_parsed.disco != p_parsed.disco:
                    continue
                result_cls = classify(item_parsed.windows, p_parsed.windows)
                if result_cls in ("exact", "upgrade"):
                    covers.append(
                        {
                            "item_id": item_info["item_id"],
                            "item_code": item_info["item_code"],
                            "item_desc": item_info["item_desc"],
                            "classification": result_cls,
                        }
                    )

        result.append(
            {
                "prearmado_id": p.id,
                "codigo": p.codigo,
                "combo_item_id": p.combo_item_id,
                "combo_item_code": p.combo_item_code,
                "combo_item_desc": p.combo_item_desc,
                "incluye_windows": p_parsed.windows if p_parsed is not None else None,
                "parsed": p_parsed_dict,
                "covers": covers,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
        )

    return result, total
