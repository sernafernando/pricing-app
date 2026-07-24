"""
Embedder-assisted TN category suggestion (sdd/tn-reconcile-publish, sub-slice
3b, design "Category" decision).

Two responsibilities, both build-once + re-runnable:

1. `sync_category_embeddings` — fetches the TN category tree (flat list with
   `parent` ids), builds a human-readable "Parent > Child" path per category,
   embeds each path with the "passage: " e5 prefix via `embed_passages`, and
   upserts into `tn_category_embedding`. Safe to re-run at any time to
   refresh the mirror (e.g. after TN categories change); it fully replaces
   the row for each `tn_category_id` rather than appending duplicates.

2. `suggest_category` — given a product's free-text category description
   (e.g. GBP `Categoría`/`SubCategoría`, optionally + title), embeds it with
   the "query: " e5 prefix via `embed_query` and returns the top-N nearest
   TN categories by pgvector cosine similarity, plus the single top-1 pick.

Both degrade gracefully to an empty/"no suggestion" result on ANY failure —
embedder down, TN API down, or (in this repo's sqlite CI test DB) no
pgvector support at all — NEVER raising, mirroring `ml_questions/
context_builder.py`'s `_similarity_query` isolation pattern: the actual
pgvector query lives in its own small function (`_similarity_query`) so
tests can mock it without a live Postgres/pgvector backend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.tn_category_embedding import TnCategoryEmbedding
from app.services.ml_questions.embedding_client import embed_passages, embed_query
from app.services.tienda_nube_product_client import TiendaNubeProductClient
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 5


def _resolve_category_name(name: Any) -> str:
    """TN category `name` may be a plain string or a `{lang: str}` dict
    (observed shapes in the TN categories API); prefer Spanish, then any
    available value, then a safe string fallback."""
    if isinstance(name, dict):
        if "es" in name and name["es"]:
            return str(name["es"])
        for value in name.values():
            if value:
                return str(value)
        return ""
    return str(name) if name is not None else ""


def build_category_paths(categories: List[Dict[str, Any]]) -> Dict[int, str]:
    """Builds `{tn_category_id: "Parent > Child > ..."}` from TN's flat
    category list (each item has `id`, `name`, and an optional `parent` id).

    Degrades gracefully: a `parent` id that doesn't resolve (missing from
    the payload, or a self/circular reference) is treated as "no parent"
    rather than raising or looping forever.
    """
    by_id: Dict[int, Dict[str, Any]] = {}
    for category in categories:
        cat_id = category.get("id")
        if cat_id is None:
            continue
        by_id[cat_id] = category

    paths: Dict[int, str] = {}

    def _path_for(cat_id: int, _seen: Optional[set] = None) -> str:
        if cat_id in paths:
            return paths[cat_id]

        seen = _seen if _seen is not None else set()
        category = by_id.get(cat_id)
        if category is None:
            return ""

        own_name = _resolve_category_name(category.get("name"))
        parent_id = category.get("parent")

        if parent_id is None or parent_id == cat_id or parent_id in seen or parent_id not in by_id:
            path = own_name
        else:
            parent_path = _path_for(parent_id, seen | {cat_id})
            path = f"{parent_path} > {own_name}" if parent_path else own_name

        paths[cat_id] = path
        return path

    for cat_id in by_id:
        _path_for(cat_id)

    return paths


def sync_category_embeddings(db: Session, client: Optional[TiendaNubeProductClient] = None) -> Dict[str, Any]:
    """Refreshes `tn_category_embedding` from the live TN category tree.

    Returns `{"synced": int, "skipped": bool, "reason": Optional[str]}`.
    Never raises — a fetch/embedder failure is logged and reported via
    `skipped`/`reason` so a caller (e.g. an admin script) can surface it
    without crashing.
    """
    active_client = client if client is not None else TiendaNubeProductClient()
    categories = _resolve(active_client.fetch_categories())

    if categories is None:
        logger.warning("sync_category_embeddings: fetch_categories failed — sync skipped")
        return {"synced": 0, "skipped": True, "reason": "fetch_categories_failed"}

    if not categories:
        return {"synced": 0, "skipped": False, "reason": None}

    paths = build_category_paths(categories)
    ordered_ids = list(paths.keys())
    path_texts = [paths[cat_id] for cat_id in ordered_ids]

    embeddings = _resolve(embed_passages(path_texts))
    if embeddings is None:
        logger.warning("sync_category_embeddings: embed_passages failed — sync skipped")
        return {"synced": 0, "skipped": True, "reason": "embed_passages_failed"}

    for cat_id, path_text, embedding in zip(ordered_ids, path_texts, embeddings):
        existing = db.query(TnCategoryEmbedding).filter(TnCategoryEmbedding.tn_category_id == cat_id).first()
        if existing:
            existing.category_path_text = path_text
            existing.embedding = embedding
        else:
            db.add(TnCategoryEmbedding(tn_category_id=cat_id, category_path_text=path_text, embedding=embedding))

    db.commit()

    return {"synced": len(ordered_ids), "skipped": False, "reason": None}


def _similarity_query(db: Session, query_embedding: List[float], top_n: int) -> List[Tuple[TnCategoryEmbedding, float]]:
    """Isolated pgvector cosine-similarity query, mirroring `ml_questions/
    context_builder.py::_similarity_query`. Kept separate so tests can mock
    it without a real Postgres/pgvector backend — the CI test DB is sqlite,
    where `embedding` is a plain JSON column and `cosine_distance` does not
    exist; calling this against sqlite raises, which the caller catches and
    treats as "no suggestion available".

    Returns `[(row, distance), ...]` ordered by ascending distance (i.e.
    descending similarity).
    """
    distance = TnCategoryEmbedding.embedding.cosine_distance(query_embedding)
    rows = db.query(TnCategoryEmbedding, distance.label("distance")).order_by(distance).limit(top_n).all()
    return [(row, dist) for row, dist in rows]


def suggest_category(db: Session, category_text: str, top_n: int = _DEFAULT_TOP_N) -> Dict[str, Any]:
    """Suggests TN categories for a free-text category description.

    Returns `{"suggestions": [{"tn_category_id", "category_path_text",
    "similarity"}, ...], "top": <same shape as suggestions[0] or None>}`.

    Returns an empty suggestion (never raises) when:
      1. `embed_query` returns `None` (embedder down/unavailable).
      2. The similarity query raises for ANY reason (e.g. sqlite CI, no
         rows, a transient DB error).
      3. The similarity query returns zero rows (empty category table).
    """
    query_embedding = _resolve(embed_query(category_text))
    if query_embedding is None:
        logger.info("suggest_category: embed_query unavailable — returning empty suggestion")
        return {"suggestions": [], "top": None}

    try:
        rows = _similarity_query(db, query_embedding, top_n)
    except Exception:
        logger.exception("suggest_category: similarity query failed — returning empty suggestion")
        return {"suggestions": [], "top": None}

    if not rows:
        return {"suggestions": [], "top": None}

    suggestions = [
        {
            "tn_category_id": row.tn_category_id,
            "category_path_text": row.category_path_text,
            "similarity": 1 - distance,
        }
        for row, distance in rows
    ]

    return {"suggestions": suggestions, "top": suggestions[0]}
