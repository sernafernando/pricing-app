"""Hay mejores ofertas: candidates vs consumer MeLi price (sale_price).

Better = higher markup OR lower price with markup ≥. Discard fingerprints
block instant re-flag; a new better novelty re-marks.
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
    if candidate_price is None or candidate_markup is None:
        return False
    if baseline_price is None or baseline_markup is None:
        return False
    if candidate_markup > baseline_markup:
        return True
    return candidate_price < baseline_price and candidate_markup >= baseline_markup


def fingerprint_mejores(mejores: Sequence[MejorTuple]) -> str:
    parts = [f"{key}:{price:g}" for key, price in sorted(mejores, key=lambda row: row[0])]
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
    """Persist flag from sale_price vs candidates. Never raises."""
    try:
        row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
        if row is None:
            return None
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
        return decision
    except Exception as exc:
        logger.warning("hay_mejores: failed for %s: %s", item_id, exc)
        return None


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
