"""Hay mejores ofertas: candidates vs consumer MeLi price (sale_price).

Better = markup↑ at same price, or lower price with markup ≥ baseline.
A higher consumer price is never better. Discard fingerprints block instant
re-flag; a new better novelty re-marks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.services.ml_promotions_pricing import (
    enriquecer_markup_por_promo,
    markup_para_precio,
    precio_de_oferta,
)
from app.services.ml_publications.parsers.seller_promotions import STATUS_CANDIDATE, promotion_key

logger = get_logger(__name__)

MejorTuple = Tuple[str, float]


@dataclass(frozen=True)
class FlagDecision:
    hay_mejores: bool
    fingerprint: Optional[str]
    descartado_fingerprint: Optional[str]


def es_mejor_oferta(
    candidate_price: Optional[float],
    candidate_markup: Optional[float],
    baseline_price: Optional[float],
    baseline_markup: Optional[float],
) -> bool:
    """Better vs status quo: markup↑ same price; markup= lower; markup↑ lower.

    Never treats a higher consumer price as better, even with higher markup.
    """
    if candidate_price is None or candidate_markup is None:
        return False
    if baseline_price is None or baseline_markup is None:
        return False
    if candidate_price > baseline_price:
        return False
    if candidate_price == baseline_price:
        return candidate_markup > baseline_markup
    return candidate_markup >= baseline_markup


def _format_fingerprint_price(price: float) -> str:
    """Fixed-point price token — never ``:g`` (collapses ≥1e6 to 6 sig digits)."""
    text = format(float(price), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fingerprint_mejores(mejores: Sequence[MejorTuple]) -> str:
    parts = [f"{key}:{_format_fingerprint_price(price)}" for key, price in sorted(mejores, key=lambda row: row[0])]
    return "|".join(parts)


def decidir_flag_hay_mejores(
    *,
    mejores: Sequence[MejorTuple],
    descartado_fingerprint: Optional[str],
) -> FlagDecision:
    if not mejores:
        return FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
    fingerprint = fingerprint_mejores(mejores)
    if descartado_fingerprint and fingerprint == descartado_fingerprint:
        return FlagDecision(
            hay_mejores=False,
            fingerprint=fingerprint,
            descartado_fingerprint=descartado_fingerprint,
        )
    return FlagDecision(hay_mejores=True, fingerprint=fingerprint, descartado_fingerprint=None)


def normalizar_entrada_seller_promo(entry: Mapping[str, Any]) -> Dict[str, Any]:
    payload = dict(entry)
    return {
        "promotion_id": entry.get("id"),
        "promotion_type": entry.get("type") or entry.get("promotion_type"),
        "status": entry.get("status"),
        "price": entry.get("price"),
        "original_price": entry.get("original_price"),
        "suggested_discounted_price": entry.get("suggested_discounted_price"),
        "name": entry.get("name"),
        "payload": payload,
    }


def listar_mejores_candidatas(
    db: Session,
    mla: str,
    candidates: Sequence[Mapping[str, Any]],
    baseline_price: float,
) -> List[MejorTuple]:
    baseline_markup = markup_para_precio(db, mla, baseline_price)
    if baseline_markup is None:
        return []
    promos = [normalizar_entrada_seller_promo(entry) for entry in candidates]
    enriquecer_markup_por_promo(db, mla, promos)
    mejores: List[MejorTuple] = []
    for entry, promo in zip(candidates, promos):
        price = precio_de_oferta(promo)
        if not es_mejor_oferta(price, promo.get("nuestro_markup"), baseline_price, baseline_markup):
            continue
        assert price is not None
        mejores.append((promotion_key(entry), float(price)))
    return mejores


def _candidate_entries(raw: Any) -> List[Mapping[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping) and e.get("status") == STATUS_CANDIDATE]


def actualizar_hay_mejores_ofertas(
    db: Session,
    item_id: str,
    *,
    raw_promotions: Any = None,
) -> Optional[FlagDecision]:
    """Persist flag from sale_price vs candidates. Never raises.

    Runs in a SAVEPOINT so a failure only skips the flag and never poisons the
    outer promotions-sync transaction. When the flag newly becomes true (or is
    re-marked with a different fingerprint), enqueues a catalog-competition
    snapshot refresh for the MLA (worker `ml_publications.catalog_competition_refresh`).
    """
    try:
        with db.begin_nested():
            row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
            if row is None:
                return None
            prev_flag = bool(row.hay_mejores_ofertas)
            prev_fingerprint = row.hay_mejores_fingerprint
            sale = db.query(MlItemSalePrice).filter(MlItemSalePrice.item_id == item_id).one_or_none()
            baseline = float(sale.amount) if sale is not None and sale.amount is not None else None
            raw = raw_promotions if raw_promotions is not None else row.raw
            candidates = _candidate_entries(raw)
            if baseline is None or baseline <= 0 or not candidates:
                decision = decidir_flag_hay_mejores(mejores=[], descartado_fingerprint=None)
            else:
                decision = decidir_flag_hay_mejores(
                    mejores=listar_mejores_candidatas(db, item_id, candidates, baseline),
                    descartado_fingerprint=row.hay_mejores_descartado_fingerprint,
                )
            row.hay_mejores_ofertas = decision.hay_mejores
            row.hay_mejores_fingerprint = decision.fingerprint
            row.hay_mejores_descartado_fingerprint = decision.descartado_fingerprint
            if decision.hay_mejores and (not prev_flag or prev_fingerprint != decision.fingerprint):
                _enqueue_catalog_competition_refresh(db, item_id)
            return decision
    except Exception as exc:
        logger.warning("hay_mejores: failed for %s: %s", item_id, exc)
        return None


def _enqueue_catalog_competition_refresh(db: Session, item_id: str) -> None:
    """Best-effort enqueue of the catalog MLA to refresh; never undoes hay_mejores.

    Runs in its own SAVEPOINT so a failed INSERT (missing table, lock, etc.)
    cannot abort the outer hay_mejores nested transaction.
    """
    try:
        from datetime import UTC, datetime

        from app.services.catalog_competition_refresh_queue import enqueue
        from app.services.catalog_competition_target import mla_for_catalog_competition_refresh

        with db.begin_nested():
            target = mla_for_catalog_competition_refresh(db, item_id)
            if target is None:
                return
            enqueue(db, [target], datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001
        logger.warning("hay_mejores: catalog competition enqueue failed for %s: %s", item_id, exc)


def descartar_hay_mejores_ofertas(db: Session, item_id: str) -> bool:
    row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
    if row is None:
        return False
    row.hay_mejores_ofertas = False
    if row.hay_mejores_fingerprint:
        row.hay_mejores_descartado_fingerprint = row.hay_mejores_fingerprint
    return True


def limpiar_hay_mejores_ofertas(db: Session, item_ids: Iterable[str]) -> None:
    ids = [item_id for item_id in item_ids if item_id]
    if not ids:
        return
    rows = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id.in_(ids)).all()
    for row in rows:
        row.hay_mejores_ofertas = False
        row.hay_mejores_fingerprint = None
        row.hay_mejores_descartado_fingerprint = None
