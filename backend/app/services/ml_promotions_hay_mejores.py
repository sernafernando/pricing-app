"""Hay mejores ofertas: candidates vs consumer MeLi price (sale_price).

Better = markup↑ at same price, or lower price with markup ≥ baseline.
A higher consumer price is never better. Discard fingerprints block instant
re-flag; a new better novelty re-marks.

Baseline markup: co-funded when a started SMART / PRE_NEGOTIATED /
PRICE_MATCHING offer matches sale_price (``markups_baseline_vigente``);
otherwise plain ``markup_para_precio(sale)``.

Ranking markup (S5, owner: "va a tener que usar el sell in sell out"): the
markups with today's sell in / sell out (``markup_sell_in_out``) when the
status quo AND the candidate both have one, else both plain markups: always
the same basis on both sides (``markups_comparables``). The sell in / sell out read is done once per call, or
once per batch of items when the caller passes it (``recompute``).

Only candidates applicable right now count (``candidata_aplicable_ahora``: writable type, started, not finished,
SELLER_CAMPAIGN only as the Premium of the month). Time passing changes that with no sync event, so the worker
handler ``ml_promotions.hay_mejores_boundaries`` re-runs the flag of the items whose candidates crossed a start or
finish date (``items_con_candidatas_que_cruzan``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.sse import sse_publish_any_process
from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.services.ml_promotions_aplicable import (
    candidata_aplicable_ahora,
    inicios_de_mes_entre,
    parse_promo_instant,
)
from app.services.ml_promotions_pricing import (
    MarkupsDePrecio,
    enriquecer_markup_por_promo,
    markups_baseline_vigente,
    precio_de_oferta,
    resolver_contexto_promos,
    resolver_sell_in_out_para_mlas,
)
from app.services.productos_sell_in_out import SellInOutBatch
from app.services.ml_publications.parsers.seller_promotions import STATUS_CANDIDATE, promotion_key

logger = get_logger(__name__)

MejorTuple = Tuple[str, float]

# The PMs' top-bar badge (`MejoresOfertasBadge`) re-reads its count on this channel.
SSE_CHANNEL_MEJORES_OFERTAS = "ml-publications:mejores-ofertas"
_CHANGED = "hay_mejores_changed"  # `Session.info` key: this transaction changed some flag
_LISTENING = "hay_mejores_listening"  # `Session.info` key: the commit/rollback listeners are on this session


def notify_hay_mejores_changed(db: Session) -> None:
    """Signal the badge once this transaction commits: never before (the count would read the old flags) and never
    on a rollback. Several changes in one transaction publish once. Best-effort, as every SSE signal."""
    db.info[_CHANGED] = True
    if not db.info.get(_LISTENING):
        db.info[_LISTENING] = True
        event.listen(db, "after_commit", _publish_if_changed)
        event.listen(db, "after_rollback", _forget_change)


def _publish_if_changed(db: Session) -> None:
    if db.info.pop(_CHANGED, False):
        sse_publish_any_process(SSE_CHANNEL_MEJORES_OFERTAS, {"hint": "reload"})


def _forget_change(db: Session) -> None:
    db.info.pop(_CHANGED, None)


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


def markups_comparables(
    candidato: MarkupsDePrecio, vigente: MarkupsDePrecio
) -> Tuple[Optional[float], Optional[float]]:
    """(candidate, status quo) markups on the SAME basis (S5): with sell in / sell out when both have it, else both
    plain, so a figure with sell in / sell out is never compared against a plain one.
    Mirrored by the frontend's ``comparableMarkups`` (pickPonerPreciosPromos.js)."""
    if candidato.markup_sell_in_out is not None and vigente.markup_sell_in_out is not None:
        return candidato.markup_sell_in_out, vigente.markup_sell_in_out
    return candidato.nuestro_markup, vigente.nuestro_markup


def _sin_sell_in_out() -> SellInOutBatch:
    """An empty sell in / sell out read: what both sides use when the shared read failed, so neither retries it."""
    return SellInOutBatch(hoy=date.today(), sell_in={}, campanas={}, bna=None)


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
        # precio_de_oferta prices a candidate DEAL at its max, as the panel and the apply do.
        "max_discounted_price": entry.get("max_discounted_price"),
        # ... and keeps a candidate LIGHTNING's suggestion within [min,max].
        "min_discounted_price": entry.get("min_discounted_price"),
        "name": entry.get("name"),
        "payload": payload,
    }


def listar_mejores_candidatas(
    db: Session,
    mla: str,
    candidates: Sequence[Mapping[str, Any]],
    baseline_price: float,
    *,
    raw_promotions: Any = None,
    sell_in_out_batch: Optional[SellInOutBatch] = None,
) -> List[MejorTuple]:
    """Candidates that beat the MeLi status quo (sale_price + correct baseline markup), compared by
    ``markups_comparables``: the same basis on both sides.

    ``raw_promotions`` (full mirror, including started) selects co-funded vs
    plain baseline via ``markups_baseline_vigente``. ``sell_in_out_batch``: a
    sell in / sell out read already done for many items; without it, one read
    for this item feeds both sides, and a failed read is not retried per side.
    The MLA's header unit is resolved ONCE and prices both sides
    (``resolver_contexto_promos``); without one, nothing beats the status quo.
    """
    if not candidates or baseline_price is None or baseline_price <= 0:
        return []
    context = resolver_contexto_promos(db, mla)
    if context is None:
        return []
    batch = sell_in_out_batch if sell_in_out_batch is not None else resolver_sell_in_out_para_mlas(db, [mla])
    if batch is None:
        batch = _sin_sell_in_out()
    vigente = markups_baseline_vigente(
        db, mla, baseline_price, raw_promotions=raw_promotions, batch=batch, context=context
    )
    if vigente.nuestro_markup is None:
        return []
    promos = [normalizar_entrada_seller_promo(entry) for entry in candidates]
    enriquecer_markup_por_promo(db, mla, promos, sell_in_out=True, batch=batch, context=context)
    mejores: List[MejorTuple] = []
    for entry, promo in zip(candidates, promos):
        price = precio_de_oferta(promo)
        candidato = MarkupsDePrecio(promo.get("nuestro_markup"), promo.get("markup_sell_in_out"))
        markup, baseline_markup = markups_comparables(candidato, vigente)
        if not es_mejor_oferta(price, markup, baseline_price, baseline_markup):
            continue
        assert price is not None
        mejores.append((promotion_key(entry), float(price)))
    return mejores


def _candidate_entries(raw: Any, now: datetime) -> List[Mapping[str, Any]]:
    """The candidates that can be applied at ``now``: a better promo applicable only in 10 days does not count."""
    if not isinstance(raw, list):
        return []
    return [
        e
        for e in raw
        if isinstance(e, Mapping) and e.get("status") == STATUS_CANDIDATE and candidata_aplicable_ahora(e, now)
    ]


# Candidate entries with a start or finish date near a window, prefiltered by the date's day so the scan never
# casts ML's free-form dates in SQL; ``items_con_candidatas_que_cruzan`` decides the exact instant in Python.
_CANDIDATE_DATES_NEAR_SQL = text(
    """
    SELECT s.item_id, e->>'start_date', e->>'finish_date'
    FROM ml_item_seller_promotions AS s
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(s.raw) = 'array' THEN s.raw ELSE '[]'::jsonb END
    ) AS e
    WHERE e->>'status' = 'candidate'
      AND (left(e->>'start_date', 10) BETWEEN :lo AND :hi OR left(e->>'finish_date', 10) BETWEEN :lo AND :hi)
    """
)


# Every item with a SELLER_CAMPAIGN candidate: at an Argentina month start its "Premium <mes>" rule flips.
_SELLER_CAMPAIGN_CANDIDATES_SQL = text(
    """
    SELECT DISTINCT s.item_id
    FROM ml_item_seller_promotions AS s
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(s.raw) = 'array' THEN s.raw ELSE '[]'::jsonb END
    ) AS e
    WHERE e->>'status' = 'candidate' AND e->>'type' = 'SELLER_CAMPAIGN'
    """
)


def items_con_candidatas_que_cruzan(db: Session, since: datetime, until: datetime) -> List[str]:
    """MLAs (sorted) whose flag time alone may have changed in ``(since, until]``: a candidate's start or finish date
    falls there, or an Argentina month starts there and the item has a SELLER_CAMPAIGN candidate (the Premium of the
    month changes). Dates are read as ``candidata_aplicable_ahora`` reads them. Postgres only."""
    lo = (since - timedelta(days=1)).date().isoformat()
    hi = (until + timedelta(days=1)).date().isoformat()
    found: Set[str] = set()
    for item_id, start, finish in db.execute(_CANDIDATE_DATES_NEAR_SQL, {"lo": lo, "hi": hi}):
        instants = (parse_promo_instant(start), parse_promo_instant(finish, end_of_day=True))
        if any(instant is not None and since < instant <= until for instant in instants):
            found.add(item_id)
    if inicios_de_mes_entre(since, until):
        found.update(row[0] for row in db.execute(_SELLER_CAMPAIGN_CANDIDATES_SQL))
    return sorted(found)


def actualizar_hay_mejores_ofertas(
    db: Session,
    item_id: str,
    *,
    raw_promotions: Any = None,
    sell_in_out_batch: Optional[SellInOutBatch] = None,
    now: Optional[datetime] = None,
) -> Optional[FlagDecision]:
    """Persist flag from sale_price vs the candidates applicable at ``now`` (default: the current instant).
    Never raises.

    Runs in a SAVEPOINT so a failure only skips the flag and never poisons the
    outer promotions-sync transaction. When the flag newly becomes true (or is
    re-marked with a different fingerprint), enqueues a catalog-competition
    snapshot refresh for the MLA (worker `ml_publications.catalog_competition_refresh`).

    While ``hay_mejores_excluido`` is true the flag stays false (permanent opt-out until a PM re-includes).
    """
    try:
        with db.begin_nested():
            row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
            if row is None:
                return None
            prev_flag = bool(row.hay_mejores_ofertas)
            prev_fingerprint = row.hay_mejores_fingerprint
            if bool(row.hay_mejores_excluido):
                decision = decidir_flag_hay_mejores(mejores=[], descartado_fingerprint=None)
                row.hay_mejores_ofertas = False
                row.hay_mejores_fingerprint = None
                row.hay_mejores_descartado_fingerprint = None
            else:
                sale = db.query(MlItemSalePrice).filter(MlItemSalePrice.item_id == item_id).one_or_none()
                baseline = float(sale.amount) if sale is not None and sale.amount is not None else None
                raw = raw_promotions if raw_promotions is not None else row.raw
                candidates = _candidate_entries(raw, now if now is not None else datetime.now(timezone.utc))
                if baseline is None or baseline <= 0 or not candidates:
                    decision = decidir_flag_hay_mejores(mejores=[], descartado_fingerprint=None)
                else:
                    decision = decidir_flag_hay_mejores(
                        mejores=listar_mejores_candidatas(
                            db,
                            item_id,
                            candidates,
                            baseline,
                            raw_promotions=raw,
                            sell_in_out_batch=sell_in_out_batch,
                        ),
                        descartado_fingerprint=row.hay_mejores_descartado_fingerprint,
                    )
                row.hay_mejores_ofertas = decision.hay_mejores
                row.hay_mejores_fingerprint = decision.fingerprint
                row.hay_mejores_descartado_fingerprint = decision.descartado_fingerprint
                if decision.hay_mejores and (not prev_flag or prev_fingerprint != decision.fingerprint):
                    _enqueue_catalog_competition_refresh(db, item_id)
        if decision.hay_mejores != prev_flag:  # after the savepoint: a failed one changed nothing
            notify_hay_mejores_changed(db)
        return decision
    except Exception as exc:
        logger.warning("hay_mejores: failed for %s: %s", item_id, exc)
        return None


def _ensure_promotions_row(db: Session, item_id: str) -> Optional[MlItemSellerPromotions]:
    """Promotions mirror row for a known MLA (stub only when the publication exists in ``ml_items``)."""
    from app.models.ml_publications import MlItem

    if db.get(MlItem, item_id) is None:
        return None
    row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
    if row is not None:
        return row
    row = MlItemSellerPromotions(item_id=item_id, raw=[], hay_mejores_ofertas=False, hay_mejores_excluido=False)
    db.add(row)
    db.flush()
    return row


def set_hay_mejores_excluido(db: Session, item_id: str, *, excluido: bool) -> bool:
    """Permanent opt-out (or re-include) for hay_mejores. Returns False when the MLA is unknown.

    Exclude: flag off, fingerprints cleared, ``hay_mejores_excluido=true`` — ``actualizar`` will not re-flag.
    Include: ``hay_mejores_excluido=false``, then recompute from the mirror.
    """
    if not item_id:
        return False
    row = _ensure_promotions_row(db, item_id)
    if row is None:
        return False
    was_flagged = bool(row.hay_mejores_ofertas)
    if excluido:
        row.hay_mejores_excluido = True
        row.hay_mejores_ofertas = False
        row.hay_mejores_fingerprint = None
        row.hay_mejores_descartado_fingerprint = None
        if was_flagged:
            notify_hay_mejores_changed(db)
        return True
    row.hay_mejores_excluido = False
    actualizar_hay_mejores_ofertas(db, item_id)
    return True


def set_hay_mejores_excluido_bulk(db: Session, item_ids: Sequence[str], *, excluido: bool) -> List[str]:
    """Exclude/include many MLAs with one promotions load (and one sell-in/out batch on re-include).

    Order preserved, duplicates dropped; unknown ``ml_items`` ids are skipped. Cap is enforced by the API (20).
    """
    from app.models.ml_publications import MlItem
    from app.services.ml_promotions_pricing import resolver_sell_in_out_para_mlas

    ids = [item_id for item_id in dict.fromkeys(item_ids) if item_id]
    if not ids:
        return []
    known = {row[0] for row in db.query(MlItem.item_id).filter(MlItem.item_id.in_(ids)).all()}
    ids = [item_id for item_id in ids if item_id in known]
    if not ids:
        return []
    rows = {
        row.item_id: row
        for row in db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id.in_(ids)).all()
    }
    for item_id in ids:
        if item_id in rows:
            continue
        stub = MlItemSellerPromotions(item_id=item_id, raw=[], hay_mejores_ofertas=False, hay_mejores_excluido=False)
        db.add(stub)
        rows[item_id] = stub
    db.flush()
    if excluido:
        any_flagged = False
        for item_id in ids:
            row = rows[item_id]
            any_flagged = any_flagged or bool(row.hay_mejores_ofertas)
            row.hay_mejores_excluido = True
            row.hay_mejores_ofertas = False
            row.hay_mejores_fingerprint = None
            row.hay_mejores_descartado_fingerprint = None
        if any_flagged:
            notify_hay_mejores_changed(db)
        return ids
    batch = resolver_sell_in_out_para_mlas(db, ids)
    for item_id in ids:
        rows[item_id].hay_mejores_excluido = False
        actualizar_hay_mejores_ofertas(db, item_id, sell_in_out_batch=batch)
    return ids


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
    if row.hay_mejores_ofertas:
        notify_hay_mejores_changed(db)
    row.hay_mejores_ofertas = False
    if row.hay_mejores_fingerprint:
        row.hay_mejores_descartado_fingerprint = row.hay_mejores_fingerprint
    return True


def limpiar_hay_mejores_ofertas(db: Session, item_ids: Iterable[str]) -> None:
    ids = [item_id for item_id in item_ids if item_id]
    if not ids:
        return
    rows = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id.in_(ids)).all()
    if any(row.hay_mejores_ofertas for row in rows):
        notify_hay_mejores_changed(db)
    for row in rows:
        row.hay_mejores_ofertas = False
        row.hay_mejores_fingerprint = None
        row.hay_mejores_descartado_fingerprint = None
