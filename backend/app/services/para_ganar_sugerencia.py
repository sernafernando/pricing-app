"""PARA GANAR suggested price + TOP board (extracted from the criterios router)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.para_ganar_catalog_seller import (
    DISPOSITION_ACTIVE,
    ParaGanarCatalogSeller,
    is_excluded,
    normalize_disposition,
)
from app.models.para_ganar_criterio_mla import ParaGanarCriterioMla
from app.services.ml_catalog_competition_service import (
    bucket_key_for_web_pricelist,
    competitor_bucket_key,
)
from app.services.para_ganar_top import (
    RankCompetitor,
    board_to_dict,
    bucket_display_label,
    compute_suggested_price,
    dense_rank_positions,
    our_rank_from_positions,
    peer_referent_notes,
)

# Keep in sync with router criterios defaults (same system values).
CRITERIOS_DEFAULT_MARKUP_MIN = 5.0
CRITERIOS_DEFAULT_TOP_SELLERS = 5


@dataclass
class SugerenciaMla:
    """Compute-only TOP board + suggested price for one MLA."""

    mla: str
    catalog_product_id: Optional[str] = None
    snapshot_at: Optional[datetime] = None
    our_price: Optional[float] = None
    our_rank: Optional[int] = None
    top_sellers: int = CRITERIOS_DEFAULT_TOP_SELLERS
    in_top: bool = False
    excluded_count: int = 0
    bucket_label: Optional[str] = None
    positions: list[dict[str, Any]] = field(default_factory=list)
    suggestion_status: str = "none"
    precio_sugerido: Optional[float] = None
    delta_ars: Optional[float] = None
    referent_nickname: Optional[str] = None
    referent_reason: Optional[str] = None
    message: Optional[str] = None
    needs_competition_refresh: bool = False


def compute_sugerencia_mla(db: Session, mla: str) -> SugerenciaMla:
    """TOP board (D12) + suggested price vs same-bucket peers.

    Raises ValueError for a blank MLA and LookupError when the publication
    is missing. Missing catalog or snapshot return a payload (do not raise).
    """
    mla_norm = (mla or "").strip().upper()
    if not mla_norm:
        raise ValueError("MLA inválida")
    if not mla_exists(db, mla_norm):
        raise LookupError("MLA no encontrada")

    catalog_product_id = catalog_product_id_for_mla(db, mla_norm)
    dispositions: dict[str, str] = {}
    if catalog_product_id:
        dispositions = {
            row.seller_id: normalize_disposition(row.disposition)
            for row in _list_persisted_sellers(db, catalog_product_id)
        }
    return _sugerencia_from_preloaded(
        mla=mla_norm,
        criterios=_effective_criterios_for_sugerencia(db, mla_norm),
        catalog_product_id=catalog_product_id,
        snap=_competition_snapshot_for_rank(db, mla=mla_norm) if catalog_product_id else None,
        dispositions=dispositions,
        cola_price=_cola_precio_for_mla(db, mla_norm),
        pricelist_id=_pricelist_id_for_mla(db, mla_norm),
    )


def compute_sugerencia_mlas_bulk(db: Session, mlas: list[str]) -> dict[str, SugerenciaMla]:
    """Assemble sugerencias for many MLAs after a few prefetch queries.

    Missing/inactive publications are omitted (same as LookupError on the
    single-MLA path). Ranking itself does not query.
    """
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in mlas:
        mla = (raw or "").strip().upper()
        if not mla or mla in seen:
            continue
        seen.add(mla)
        wanted.append(mla)
    if not wanted:
        return {}

    pubs = _bulk_publications(db, wanted)
    criterios_by_mla = _bulk_criterios(db, wanted)
    catalog_by_mla = _bulk_catalog_product_ids(db, wanted)
    snaps_by_mla = _bulk_competition_snapshots(db, wanted)
    catalog_ids = sorted({cid for cid in catalog_by_mla.values() if cid})
    sellers_by_catalog = _bulk_persisted_sellers(db, catalog_ids)

    out: dict[str, SugerenciaMla] = {}
    for mla in wanted:
        pub = pubs.get(mla)
        if not pub or not pub["activo"]:
            continue
        catalog_product_id = catalog_by_mla.get(mla)
        sellers = sellers_by_catalog.get(catalog_product_id or "", [])
        dispositions = {seller_id: normalize_disposition(disp) for seller_id, disp in sellers}
        out[mla] = _sugerencia_from_preloaded(
            mla=mla,
            criterios=criterios_by_mla.get(mla) or _default_criterios(),
            catalog_product_id=catalog_product_id,
            snap=snaps_by_mla.get(mla) if catalog_product_id else None,
            dispositions=dispositions,
            cola_price=pub["cola_price"],
            pricelist_id=pub["pricelist_id"],
        )
    return out


def _sugerencia_from_preloaded(
    *,
    mla: str,
    criterios: dict[str, Any],
    catalog_product_id: Optional[str],
    snap: Optional[dict[str, Any]],
    dispositions: dict[str, str],
    cola_price: Optional[float],
    pricelist_id: Optional[int],
) -> SugerenciaMla:
    """Rank + suggested price from already-loaded rows (no DB)."""
    top_n = int(criterios["top_sellers"])
    if not catalog_product_id:
        return SugerenciaMla(
            mla=mla,
            top_sellers=top_n,
            message="Sin catálogo vinculado: no hay snapshot de competencia para rankear.",
            needs_competition_refresh=False,
        )
    if not snap:
        return SugerenciaMla(
            mla=mla,
            catalog_product_id=catalog_product_id,
            top_sellers=top_n,
            message=(
                "Sin snapshot de competencia OK para esta MLA. "
                "Actualizá la competencia de esta publicación (no alcanza el snapshot de otra lista/cuotas del mismo catálogo)."
            ),
            needs_competition_refresh=True,
        )

    excluded_count = sum(1 for d in dispositions.values() if d != DISPOSITION_ACTIVE)

    our_seller_id = str(snap["our_seller_id"]).strip() if snap.get("our_seller_id") else None
    our_item_id = str(snap["our_item_id"]).strip() if snap.get("our_item_id") else mla
    our_price = _positive_price(snap.get("our_price")) or cola_price
    our_bucket_key = snap.get("our_bucket_key")
    if isinstance(our_bucket_key, str):
        our_bucket_key = our_bucket_key.strip() or None
    else:
        our_bucket_key = None
    if not our_bucket_key:
        our_bucket_key = bucket_key_for_web_pricelist(pricelist_id)

    competitors_raw = snap.get("competitors") or []
    if isinstance(competitors_raw, str):
        try:
            competitors_raw = json.loads(competitors_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            competitors_raw = []
    if not isinstance(competitors_raw, list):
        competitors_raw = []

    best_by_seller: dict[str, RankCompetitor] = {}
    for competitor in competitors_raw:
        if not isinstance(competitor, dict):
            continue
        raw_id = competitor.get("seller_id")
        if raw_id is None:
            continue
        seller_id = str(raw_id).strip()
        if not seller_id:
            continue
        price_ars = _positive_price(competitor.get("price_ars"))
        if price_ars is None:
            continue
        is_us = (our_seller_id and seller_id == our_seller_id) or (
            competitor.get("item_id") is not None and str(competitor.get("item_id")).strip() == mla
        )
        if not is_us and not _competitor_in_our_bucket(competitor, our_bucket_key):
            continue
        if not is_us and is_excluded(dispositions.get(seller_id)):
            continue
        nickname = competitor.get("seller_nickname")
        nickname_s = str(nickname).strip()[:128] if nickname else None
        item_raw = competitor.get("item_id")
        item_id = str(item_raw).strip()[:32] if item_raw else None
        label_raw = competitor.get("listing_label")
        listing_label = str(label_raw).strip()[:64] if label_raw else None
        markup_val = competitor.get("markup")
        markup_f: Optional[float] = None
        if markup_val is not None:
            try:
                markup_f = float(markup_val)
            except (TypeError, ValueError):
                markup_f = None
        candidate = RankCompetitor(
            seller_id=seller_id,
            nickname=nickname_s,
            item_id=item_id,
            price_ars=price_ars,
            is_us=bool(is_us),
            listing_label=listing_label,
            markup=markup_f,
        )
        previous = best_by_seller.get(seller_id)
        if previous is None or candidate.price_ars < previous.price_ars or (candidate.is_us and not previous.is_us):
            best_by_seller[seller_id] = candidate

    ranked: list[RankCompetitor] = list(best_by_seller.values())
    seen_sellers = set(best_by_seller.keys())
    our_listing_label = bucket_display_label(our_bucket_key)

    if our_price is not None and our_seller_id and our_seller_id not in seen_sellers:
        ranked.append(
            RankCompetitor(
                seller_id=our_seller_id,
                nickname="Nosotros",
                item_id=our_item_id,
                price_ars=our_price,
                is_us=True,
                listing_label=our_listing_label,
            )
        )
    elif our_price is not None and not any(c.is_us for c in ranked):
        ranked.append(
            RankCompetitor(
                seller_id=our_seller_id or "us",
                nickname="Nosotros",
                item_id=our_item_id,
                price_ars=our_price,
                is_us=True,
                listing_label=our_listing_label,
            )
        )

    peer_label = next((c.listing_label for c in ranked if c.listing_label and not c.is_us), None)
    bucket_label = bucket_display_label(our_bucket_key, listing_label=peer_label)

    positions = dense_rank_positions(ranked)
    our_rank = our_rank_from_positions(positions)
    payload = board_to_dict(
        positions=positions,
        top_n=top_n,
        our_price=our_price,
        our_rank=our_rank,
        excluded_count=excluded_count,
        catalog_product_id=catalog_product_id,
        snapshot_at=None,
        bucket_label=bucket_label,
    )
    message_parts: list[str] = []
    if excluded_count > 0:
        noun = "seller" if excluded_count == 1 else "sellers"
        adj = "excluido" if excluded_count == 1 else "excluidos"
        message_parts.append(
            f"Hay {excluded_count} {noun} {adj} del ranking (siguen en la lista de Criterios para reactivarlos)."
        )
    positions_available = len(positions)
    if positions_available < top_n:
        if positions_available == 0:
            message_parts.append(f"No hay posiciones de precio en este bucket para armar el TOP {top_n}.")
        else:
            pos_word = "posición" if positions_available == 1 else "posiciones"
            message_parts.append(
                f"En este bucket solo hay {positions_available} {pos_word} de precio; "
                f"el TOP pide {top_n} (faltan competidores)."
            )
    suggested = compute_suggested_price(
        ranked,
        markup_min=criterios["markup_min"],
        precio_min=criterios["precio_min"],
        precio_max=criterios["precio_max"],
    )
    suggestion_status = suggested.suggestion_status if suggested else "alone"
    if suggested is None and not any(not c.is_us for c in ranked):
        suggestion_status = "alone"
    elif suggested is None:
        suggestion_status = "none"

    notes = peer_referent_notes(
        ranked,
        markup_min=criterios["markup_min"],
        precio_min=criterios["precio_min"],
        precio_max=criterios["precio_max"],
        referent_seller_id=suggested.referent_seller_id if suggested else None,
    )
    for position in payload["positions"]:
        for seller in position["sellers"]:
            seller["referent_note"] = notes.get(seller["seller_id"])

    message = " ".join(message_parts) if message_parts else None
    snapshot_at = snap.get("fecha_consulta")
    if isinstance(snapshot_at, str):
        try:
            snapshot_at = datetime.fromisoformat(snapshot_at.replace("Z", "+00:00"))
        except ValueError:
            snapshot_at = None
    return SugerenciaMla(
        mla=mla,
        catalog_product_id=payload["catalog_product_id"],
        snapshot_at=snapshot_at if isinstance(snapshot_at, datetime) else None,
        our_price=payload["our_price"],
        our_rank=payload["our_rank"],
        top_sellers=payload["top_sellers"],
        in_top=payload["in_top"],
        excluded_count=payload["excluded_count"],
        bucket_label=payload.get("bucket_label"),
        positions=list(payload["positions"]),
        suggestion_status=suggestion_status,
        precio_sugerido=suggested.precio_sugerido if suggested else None,
        delta_ars=suggested.delta_ars if suggested else None,
        referent_nickname=suggested.referent_nickname if suggested else None,
        referent_reason=suggested.referent_reason if suggested else None,
        message=message,
        needs_competition_refresh=False,
    )


def _default_criterios() -> dict[str, Any]:
    return {
        "top_sellers": CRITERIOS_DEFAULT_TOP_SELLERS,
        "markup_min": CRITERIOS_DEFAULT_MARKUP_MIN,
        "precio_min": None,
        "precio_max": None,
    }


def _criterios_from_row(row: ParaGanarCriterioMla) -> dict[str, Any]:
    top_sellers = row.top_sellers if row.top_sellers is not None else CRITERIOS_DEFAULT_TOP_SELLERS
    return {
        "top_sellers": int(top_sellers),
        "markup_min": _as_float(row.markup_min),
        "precio_min": _as_float(row.precio_min),
        "precio_max": _as_float(row.precio_max),
    }


def _effective_criterios_for_sugerencia(db: Session, mla: str) -> dict[str, Any]:
    row = db.query(ParaGanarCriterioMla).filter(ParaGanarCriterioMla.mla == mla).first()
    if row is None:
        return _default_criterios()
    return _criterios_from_row(row)


def mla_exists(db: Session, mla: str) -> bool:
    found = db.execute(
        text("SELECT 1 FROM publicaciones_ml WHERE mla = :mla AND activo = true LIMIT 1"),
        {"mla": mla},
    ).first()
    return found is not None


def catalog_product_id_for_mla(db: Session, mla: str) -> Optional[str]:
    try:
        link = db.execute(
            text(
                """
                SELECT catalog_product_id
                FROM ml_publication_links
                WHERE mla = :mla AND catalog_product_id IS NOT NULL
                LIMIT 1
                """
            ),
            {"mla": mla},
        ).first()
        if link and link[0]:
            return str(link[0])
    except (OperationalError, ProgrammingError):
        db.rollback()

    try:
        snap = db.execute(
            text(
                """
                SELECT catalog_product_id
                FROM ml_catalog_competition
                WHERE mla = :mla AND catalog_product_id IS NOT NULL
                ORDER BY fecha_consulta DESC
                LIMIT 1
                """
            ),
            {"mla": mla},
        ).first()
        if snap and snap[0]:
            return str(snap[0])
    except (OperationalError, ProgrammingError):
        db.rollback()
    return None


def _list_persisted_sellers(db: Session, catalog_product_id: str) -> list[ParaGanarCatalogSeller]:
    return (
        db.query(ParaGanarCatalogSeller)
        .filter(ParaGanarCatalogSeller.catalog_product_id == catalog_product_id)
        .order_by(ParaGanarCatalogSeller.nickname.nulls_last(), ParaGanarCatalogSeller.seller_id)
        .all()
    )


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_price(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def _competition_snapshot_for_rank(db: Session, *, mla: str) -> Optional[dict[str, Any]]:
    try:
        snap = (
            db.execute(
                text(
                    """
                SELECT mla, competitors, fecha_consulta, our_price, our_seller_id,
                       our_item_id, our_bucket_key
                FROM ml_catalog_competition
                WHERE mla = :mla
                  AND fetch_status = 'ok'
                  AND competitors IS NOT NULL
                ORDER BY fecha_consulta DESC
                LIMIT 1
                """
                ),
                {"mla": mla},
            )
            .mappings()
            .first()
        )
    except (OperationalError, ProgrammingError):
        db.rollback()
        return None
    return dict(snap) if snap else None


def _competitor_in_our_bucket(competitor: dict[str, Any], our_bucket_key: Optional[str]) -> bool:
    if not our_bucket_key:
        return False
    if competitor_bucket_key(competitor) == our_bucket_key:
        return True
    if competitor.get("same_bucket") is True and competitor.get("bucket_key") == our_bucket_key:
        return True
    return False


def _pricelist_id_for_mla(db: Session, mla: str) -> Optional[int]:
    row = db.execute(
        text("SELECT pricelist_id FROM publicaciones_ml WHERE mla = :mla LIMIT 1"),
        {"mla": mla},
    ).first()
    if not row or row[0] is None:
        return None
    return int(row[0])


def _cola_precio_for_mla(db: Session, mla: str) -> Optional[float]:
    row = (
        db.execute(
            text(
                """
                SELECT pm.precio
                FROM publicaciones_ml p
                LEFT JOIN precios_ml pm
                  ON pm.item_id = p.item_id AND pm.pricelist_id = p.pricelist_id
                WHERE p.mla = :mla
                LIMIT 1
                """
            ),
            {"mla": mla},
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    return _positive_price(row["precio"])


def _in_clause(values: list[str], *, prefix: str) -> tuple[str, dict[str, str]]:
    params = {f"{prefix}_{i}": value for i, value in enumerate(values)}
    clause = ", ".join(f":{prefix}_{i}" for i in range(len(values)))
    return clause, params


def _bulk_publications(db: Session, mlas: list[str]) -> dict[str, dict[str, Any]]:
    clause, params = _in_clause(mlas, prefix="pub")
    rows = (
        db.execute(
            text(
                f"""
                SELECT p.mla, p.activo, p.pricelist_id, pm.precio
                FROM publicaciones_ml p
                LEFT JOIN precios_ml pm
                  ON pm.item_id = p.item_id AND pm.pricelist_id = p.pricelist_id
                WHERE p.mla IN ({clause})
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        mla = str(row["mla"]).strip().upper()
        out[mla] = {
            "activo": bool(row["activo"]),
            "pricelist_id": int(row["pricelist_id"]) if row["pricelist_id"] is not None else None,
            "cola_price": _positive_price(row["precio"]),
        }
    return out


def _bulk_criterios(db: Session, mlas: list[str]) -> dict[str, dict[str, Any]]:
    rows = db.query(ParaGanarCriterioMla).filter(ParaGanarCriterioMla.mla.in_(mlas)).all()
    return {row.mla: _criterios_from_row(row) for row in rows}


def _bulk_catalog_product_ids(db: Session, mlas: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    clause, params = _in_clause(mlas, prefix="cat")
    try:
        rows = db.execute(
            text(
                f"""
                SELECT mla, catalog_product_id
                FROM ml_publication_links
                WHERE mla IN ({clause}) AND catalog_product_id IS NOT NULL
                """
            ),
            params,
        ).all()
        for mla, catalog_id in rows:
            if catalog_id:
                out[str(mla).strip().upper()] = str(catalog_id)
    except (OperationalError, ProgrammingError):
        db.rollback()

    missing = [mla for mla in mlas if mla not in out]
    if not missing:
        return out
    clause, params = _in_clause(missing, prefix="snapcat")
    try:
        rows = db.execute(
            text(
                f"""
                SELECT mla, catalog_product_id, fecha_consulta
                FROM ml_catalog_competition
                WHERE mla IN ({clause}) AND catalog_product_id IS NOT NULL
                ORDER BY fecha_consulta DESC
                """
            ),
            params,
        ).all()
    except (OperationalError, ProgrammingError):
        db.rollback()
        return out
    for mla, catalog_id, _fecha in rows:
        key = str(mla).strip().upper()
        if key in out or not catalog_id:
            continue
        out[key] = str(catalog_id)
    return out


def _bulk_competition_snapshots(db: Session, mlas: list[str]) -> dict[str, dict[str, Any]]:
    clause, params = _in_clause(mlas, prefix="snap")
    try:
        rows = (
            db.execute(
                text(
                    f"""
                    SELECT mla, competitors, fecha_consulta, our_price, our_seller_id,
                           our_item_id, our_bucket_key
                    FROM ml_catalog_competition
                    WHERE mla IN ({clause})
                      AND fetch_status = 'ok'
                      AND competitors IS NOT NULL
                    ORDER BY fecha_consulta DESC
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
    except (OperationalError, ProgrammingError):
        db.rollback()
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        mla = str(row["mla"]).strip().upper()
        if mla in out:
            continue
        out[mla] = dict(row)
    return out


def _bulk_persisted_sellers(db: Session, catalog_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    if not catalog_ids:
        return {}
    rows = db.query(ParaGanarCatalogSeller).filter(ParaGanarCatalogSeller.catalog_product_id.in_(catalog_ids)).all()
    out: dict[str, list[tuple[str, str]]] = {cid: [] for cid in catalog_ids}
    for row in rows:
        out.setdefault(row.catalog_product_id, []).append((row.seller_id, row.disposition))
    return out
