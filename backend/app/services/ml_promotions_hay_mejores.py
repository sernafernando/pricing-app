"""Hay mejores ofertas: candidates vs consumer MeLi price (sale_price).

Better = markup↑ at same price, or lower price with markup ≥ baseline.
A higher consumer price is never better. Discard fingerprints block instant
re-flag; a new better novelty re-marks.

Baseline: the Activa ahora offer ML applies (lowest-price ``started``, via
``markups_baseline_vigente`` / ``derivar_application_status``); otherwise plain
``markup_para_precio(sale)`` against sale.

Ranking markup (S5, owner: "va a tener que usar el sell in sell out"): the
markups with today's sell in / sell out (``markup_sell_in_out``) when the
status quo AND the candidate both have one, else both plain markups: always
the same basis on both sides (``markups_comparables``). The sell in / sell out read is done once per call, or
once per batch of items when the caller passes it (``recompute``).

Only candidates applicable right now count (``candidata_aplicable_ahora``: writable type, started, not finished,
SELLER_CAMPAIGN only as the Premium of the month). Time passing changes that with no sync event, so the worker
handler ``ml_promotions.hay_mejores_boundaries`` re-runs the flag of the items whose candidates crossed a start or
finish date (``items_con_candidatas_que_cruzan``) and, every tick, every currently flagged row (stale-flag hygiene).
A ``sale_price`` mirror write also recomputes the flag (same as a promotions write).
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
from app.services.ml_catalog_competition_service import (
    effective_same_bucket_competitors,
    min_rival_price_ars,
    obtener_ultimo_snapshot,
    snapshot_is_fresh,
)
from app.services.ml_hay_mejores_audit_service import record_flag_transition
from app.services.ml_hay_mejores_criterios_service import (
    CriteriosView,
    catalog_win_con_precio,
    get_criterios,
    markup_pasa_c1,
    markup_pasa_c2,
    monopolio_c6_oportunidad,
)

logger = get_logger(__name__)

MejorTuple = Tuple[str, float]

# Synthetic fingerprint key for C6 raise-price opportunity (not a MeLi promotion id).
C6_FINGERPRINT_KEY = "c6"
AUTOAPPLY_FAIL_PREFIX = "Autoapply falló"


@dataclass(frozen=True)
class MejoresEvaluacion:
    """Ranking result plus lean-audit snapshot (status quo, beating candidates, criteria)."""

    mejores: List[MejorTuple]
    status_quo: Dict[str, Any]
    candidatas: List[Dict[str, Any]]
    criterios: Dict[str, Any]
    monopolio: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class MonopolioEvaluacion:
    """C6 raise-price opportunity on effective catalog ranking."""

    oportunidad: Dict[str, float]
    flag_tuple: MejorTuple
    solo_via_promo: bool


def _criterios_audit_dict(criterios: CriteriosView) -> Dict[str, Any]:
    return {
        "c1_activo": criterios.c1_activo,
        "c1_markup_min": float(criterios.c1_markup_min) if criterios.c1_markup_min is not None else None,
        "c1_markup_max": float(criterios.c1_markup_max) if criterios.c1_markup_max is not None else None,
        "c2_activo": criterios.c2_activo,
        "c2_solo_markup_positivo": criterios.c2_solo_markup_positivo,
        "c6_activo": criterios.c6_activo,
        "c6_solo_via_promo": criterios.c6_solo_via_promo,
        "c6_gap_min": float(criterios.c6_gap_min),
        "c6_distancia_objetivo": float(criterios.c6_distancia_objetivo),
        "auto_aplicacion": criterios.auto_aplicacion,
        "sellers_excluidos": list(criterios.sellers_excluidos),
    }


# The PMs' top-bar badge (`MejoresOfertasBadge`) re-reads its count on this channel.
SSE_CHANNEL_MEJORES_OFERTAS = "ml-publications:mejores-ofertas"
_CHANGED = "hay_mejores_changed"  # `Session.info` key: this transaction changed some flag
_LISTENING = "hay_mejores_listening"  # `Session.info` key: the commit/rollback listeners are on this session
# R-AUTO jobs run only after the outer txn commits (ADR-5: never hold a Session across MeLi HTTP).
_AUTO_PENDING = "hay_mejores_auto_pending"


@dataclass(frozen=True)
class FlagDecision:
    hay_mejores: bool
    fingerprint: Optional[str]
    descartado_fingerprint: Optional[str]


def _ensure_hay_mejores_listeners(db: Session) -> None:
    if db.info.get(_LISTENING):
        return
    db.info[_LISTENING] = True
    event.listen(db, "after_commit", _on_hay_mejores_commit)
    event.listen(db, "after_rollback", _on_hay_mejores_rollback)


def notify_hay_mejores_changed(db: Session) -> None:
    """Signal the badge once this transaction commits: never before (the count would read the old flags) and never
    on a rollback. Several changes in one transaction publish once. Best-effort, as every SSE signal."""
    db.info[_CHANGED] = True
    _ensure_hay_mejores_listeners(db)


def _schedule_auto_enroll(
    db: Session,
    item_id: str,
    target: Mapping[str, Any],
    decision: FlagDecision,
) -> None:
    """Queue R-AUTO enroll for after_commit so MeLi HTTP never holds the caller's Session."""
    pending: List[Dict[str, Any]] = db.info.setdefault(_AUTO_PENDING, [])
    pending.append(
        {
            "item_id": item_id,
            "target": dict(target),
            "fingerprint": decision.fingerprint,
            "descartado_fingerprint": decision.descartado_fingerprint,
        }
    )
    _ensure_hay_mejores_listeners(db)


def _on_hay_mejores_commit(db: Session) -> None:
    if db.info.pop(_CHANGED, False):
        sse_publish_any_process(SSE_CHANNEL_MEJORES_OFERTAS, {"hint": "reload"})
    pending = list(db.info.pop(_AUTO_PENDING, []) or [])
    for job in pending:
        _run_auto_enroll_after_commit(job)


def _on_hay_mejores_rollback(db: Session) -> None:
    db.info.pop(_CHANGED, None)
    db.info.pop(_AUTO_PENDING, None)


def _auto_still_authorized(db: Session, item_id: str, target: Optional[Mapping[str, Any]] = None) -> bool:
    """Fresh read: Auto still ON, permiso holds, and C1 still accepts the pick markup when known."""
    from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios
    from app.models.usuario import Usuario
    from app.services.ml_hay_mejores_criterios_service import PERMISO_AUTO_APLICACION, get_criterios
    from app.services.permisos_service import PermisosService

    view = get_criterios(db, item_id)
    if not view.auto_aplicacion or not view.exists:
        return False
    row = db.get(MlHayMejoresCriterios, item_id)
    updated_by = getattr(row, "updated_by", None) if row is not None else None
    if updated_by is None:
        return False
    user = db.get(Usuario, int(updated_by))
    if user is None:
        return False
    if not bool(PermisosService(db).tiene_permiso(user, PERMISO_AUTO_APLICACION)):
        return False
    # Re-check C1 at enroll time (suggestion): refuse if the pick markup left the band.
    if target is not None and "markup_visto" in target:
        markup = target.get("markup_visto")
        if markup is not None and not markup_pasa_c1(
            float(markup),
            c1_activo=view.c1_activo,
            c1_markup_min=view.c1_markup_min,
            c1_markup_max=view.c1_markup_max,
        ):
            return False
    return True


def _run_auto_enroll_after_commit(job: Mapping[str, Any]) -> None:
    """HTTP enroll with no caller Session held; on fail, re-flag in a fresh short session."""
    item_id = str(job["item_id"])
    target = job["target"]
    pick_key = str(target.get("key") or "") if isinstance(target, Mapping) else ""
    try:
        from app.core.database import get_background_db

        with get_background_db() as gate_db:
            authorized = _auto_still_authorized(gate_db, item_id, target if isinstance(target, Mapping) else None)
        if not authorized:
            logger.info("hay_mejores R-AUTO skipped for %s: Auto off, permiso revoked, or C1", item_id)
            return
    except Exception as exc:
        logger.warning("hay_mejores R-AUTO gate failed for %s: %s", item_id, exc, exc_info=True)
        return

    outcome = _try_auto_enroll(item_id, target)
    if _auto_enroll_succeeded(outcome):
        try:
            from app.core.database import get_background_db

            with get_background_db() as done_db:
                row = (
                    done_db.query(MlItemSellerPromotions)
                    .filter(MlItemSellerPromotions.item_id == item_id)
                    .with_for_update()
                    .one_or_none()
                )
                parsed = _parse_auto_pending(getattr(row, "hay_mejores_fingerprint", None) if row else None)
                if row is not None and parsed is not None and (not pick_key or parsed[0] == pick_key):
                    row.hay_mejores_fingerprint = None
                    row.hay_mejores_ofertas = False
        except Exception as exc:
            logger.warning("hay_mejores R-AUTO clear-pending failed for %s: %s", item_id, exc, exc_info=True)
        return
    if _auto_enroll_is_ambiguous(outcome):
        # Leave auto_pending fingerprint; next recompute of the same pick must not re-queue.
        logger.info("hay_mejores R-AUTO ambiguous for %s pick=%s — leaving pending", item_id, pick_key)
        return
    fail_reason = _auto_enroll_fail_reason(outcome)
    try:
        from app.core.database import get_background_db

        with get_background_db() as fresh_db:
            row = (
                fresh_db.query(MlItemSellerPromotions)
                .filter(MlItemSellerPromotions.item_id == item_id)
                .with_for_update()
                .one_or_none()
            )
            if row is None:
                return
            row.hay_mejores_ofertas = True
            row.hay_mejores_fingerprint = job.get("fingerprint")
            row.hay_mejores_descartado_fingerprint = job.get("descartado_fingerprint")
            _enqueue_catalog_competition_refresh(fresh_db, item_id)
            record_flag_transition(
                fresh_db,
                item_id,
                payload={
                    "fingerprint": job.get("fingerprint"),
                    "auto_aplicacion": True,
                    "auto_fail": True,
                    "auto_fail_message": f"{AUTOAPPLY_FAIL_PREFIX}: {fail_reason}",
                    "auto_pick": target.get("key") if isinstance(target, Mapping) else None,
                },
            )
            notify_hay_mejores_changed(fresh_db)
    except Exception as exc:
        logger.warning("hay_mejores R-AUTO re-flag after fail failed for %s: %s", item_id, exc, exc_info=True)


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


def evaluar_mejores_candidatas(
    db: Session,
    mla: str,
    candidates: Sequence[Mapping[str, Any]],
    baseline_price: float,
    *,
    raw_promotions: Any = None,
    sell_in_out_batch: Optional[SellInOutBatch] = None,
) -> MejoresEvaluacion:
    """Same ranking as ``listar_mejores_candidatas``, plus audit snapshot fields."""
    empty = MejoresEvaluacion(mejores=[], status_quo={}, candidatas=[], criterios={})
    if not candidates or baseline_price is None or baseline_price <= 0:
        return empty
    context = resolver_contexto_promos(db, mla)
    if context is None:
        return empty
    batch = sell_in_out_batch if sell_in_out_batch is not None else resolver_sell_in_out_para_mlas(db, [mla])
    if batch is None:
        batch = _sin_sell_in_out()
    vigente = markups_baseline_vigente(
        db, mla, baseline_price, raw_promotions=raw_promotions, batch=batch, context=context
    )
    if vigente.nuestro_markup is None:
        return empty
    status_quo_price = (
        float(vigente.precio_status_quo)
        if vigente.precio_status_quo is not None and vigente.precio_status_quo > 0
        else float(baseline_price)
    )
    promos = [normalizar_entrada_seller_promo(entry) for entry in candidates]
    enriquecer_markup_por_promo(db, mla, promos, sell_in_out=True, batch=batch, context=context)
    criterios = get_criterios(db, mla)
    min_rival: Optional[float] = None
    # C2 only flags when status quo is *not* already #1 (effective). If we already win,
    # keep the toggle ON for later loss-of-position, but do not surface worse promos.
    c2_busca_ganar = False
    snapshot = None
    if criterios.c2_activo or criterios.c6_activo:
        snapshot = obtener_ultimo_snapshot(db, mla)
        if not snapshot_is_fresh(snapshot):
            # One enqueue per evaluate when the snapshot is missing/stale (not per rival).
            _enqueue_catalog_competition_refresh(db, mla)
            snapshot = None
    if criterios.c2_activo:
        if snapshot is not None:
            min_rival = min_rival_price_ars(
                snapshot,
                our_item_id=mla,
                sellers_excluidos=criterios.sellers_excluidos,
            )
        ya_ganamos = catalog_win_con_precio(status_quo_price, min_rival)
        c2_busca_ganar = min_rival is not None and not ya_ganamos
    # C6 raise-assist: promos that raise price while still winning the effective catalog.
    c6_segundo: Optional[float] = None
    c6_busca_asistir = False
    if criterios.c6_activo and snapshot is not None:
        c6_segundo = min_rival_price_ars(
            snapshot,
            our_item_id=mla,
            sellers_excluidos=criterios.sellers_excluidos,
        )
        c6_opp = monopolio_c6_oportunidad(
            c6_activo=True,
            our_price_ars=status_quo_price,
            segundo_precio_ars=c6_segundo,
            c6_gap_min=criterios.c6_gap_min,
            c6_distancia_objetivo=criterios.c6_distancia_objetivo,
        )
        c6_busca_asistir = c6_opp is not None
    mejores: List[MejorTuple] = []
    candidatas: List[Dict[str, Any]] = []
    for entry, promo in zip(candidates, promos):
        price = precio_de_oferta(promo)
        candidato = MarkupsDePrecio(promo.get("nuestro_markup"), promo.get("markup_sell_in_out"))
        markup, baseline_markup = markups_comparables(candidato, vigente)
        pasa_clasico = es_mejor_oferta(price, markup, status_quo_price, baseline_markup) and markup_pasa_c1(
            markup,
            c1_activo=criterios.c1_activo,
            c1_markup_min=criterios.c1_markup_min,
            c1_markup_max=criterios.c1_markup_max,
        )
        # Owner: C1 always wins — C2/Auto may only suggest/apply inside the C1 band.
        pasa_c2 = (
            c2_busca_ganar
            and catalog_win_con_precio(price, min_rival)
            and markup_pasa_c2(
                markup,
                c2_activo=criterios.c2_activo,
                c2_solo_markup_positivo=criterios.c2_solo_markup_positivo,
            )
            and markup_pasa_c1(
                markup,
                c1_activo=criterios.c1_activo,
                c1_markup_min=criterios.c1_markup_min,
                c1_markup_max=criterios.c1_markup_max,
            )
        )
        # Raise-assist: higher consumer price than status quo, still #1, inside C1.
        pasa_c6 = (
            c6_busca_asistir
            and price is not None
            and markup is not None
            and float(price) > float(status_quo_price)
            and catalog_win_con_precio(float(price), c6_segundo)
            and markup_pasa_c1(
                markup,
                c1_activo=criterios.c1_activo,
                c1_markup_min=criterios.c1_markup_min,
                c1_markup_max=criterios.c1_markup_max,
            )
        )
        if not pasa_clasico and not pasa_c2 and not pasa_c6:
            continue
        assert price is not None
        key = promotion_key(entry)
        mejores.append((key, float(price)))
        candidatas.append(
            {
                "key": key,
                "price": float(price),
                "markup": markup,
                "markup_status_quo": baseline_markup,
                "nuestro_markup": promo.get("nuestro_markup"),
                "markup_sell_in_out": promo.get("markup_sell_in_out"),
                "path_clasico": bool(pasa_clasico),
                "path_c2": bool(pasa_c2),
                "path_c6": bool(pasa_c6),
            }
        )
    return MejoresEvaluacion(
        mejores=mejores,
        status_quo={
            "price": status_quo_price,
            "nuestro_markup": vigente.nuestro_markup,
            "markup_sell_in_out": vigente.markup_sell_in_out,
            "precio_status_quo": vigente.precio_status_quo,
            "sale_baseline": float(baseline_price),
        },
        candidatas=candidatas,
        criterios=_criterios_audit_dict(criterios),
    )


def listar_mejores_candidatas(
    db: Session,
    mla: str,
    candidates: Sequence[Mapping[str, Any]],
    baseline_price: float,
    *,
    raw_promotions: Any = None,
    sell_in_out_batch: Optional[SellInOutBatch] = None,
) -> List[MejorTuple]:
    """Candidates that beat the MeLi status quo, compared by ``markups_comparables``.

    Status quo comes from ``markups_baseline_vigente``: the lowest-price started
    offer ML applies (Activa ahora), else plain sale. ``baseline_price`` is the
    sale used for that plain fallback. ``raw_promotions`` is the full mirror
    (incl. started). ``sell_in_out_batch``: a sell in / sell out read already
    done for many items; without it, one read for this item feeds both sides.
    The MLA's header unit is resolved ONCE (``resolver_contexto_promos``);
    without one, nothing beats the status quo.
    """
    return evaluar_mejores_candidatas(
        db,
        mla,
        candidates,
        baseline_price,
        raw_promotions=raw_promotions,
        sell_in_out_batch=sell_in_out_batch,
    ).mejores


def _our_price_ars_from_snapshot(row: Any, our_item_id: str) -> Optional[float]:
    """Our ``price_ars`` from the snapshot competitor list (same currency basis as rivals)."""
    if row is None:
        return None
    for competitor in effective_same_bucket_competitors(row, sellers_excluidos=None):
        if (competitor.get("item_id") or "") == our_item_id and competitor.get("price_ars") is not None:
            return float(competitor["price_ars"])
    for competitor in row.competitors or []:
        if (competitor.get("item_id") or "") == our_item_id and competitor.get("price_ars") is not None:
            return float(competitor["price_ars"])
    return None


def evaluar_monopolio_c6(
    db: Session,
    mla: str,
    *,
    criterios: Optional[CriteriosView] = None,
    our_price_ars: Optional[float] = None,
) -> Optional[MonopolioEvaluacion]:
    """C6: we are #1 on effective ranking and gap to 2nd ≥ gap mín → raise-price opportunity.

    Inert without snapshot / rivals / ``c6_activo``. Does not enroll; only shapes the flag fingerprint.
    ``our_price_ars`` should be the live sale price when the caller has it (not a stale snapshot).
    Fingerprint uses a stable ``c6:1`` marker so $1 moves of the 2nd rival do not churn discard/audit.
    """
    view = criterios if criterios is not None else get_criterios(db, mla)
    if not view.c6_activo:
        return None
    snapshot = obtener_ultimo_snapshot(db, mla)
    if not snapshot_is_fresh(snapshot):
        _enqueue_catalog_competition_refresh(db, mla)
        return None
    segundo = min_rival_price_ars(
        snapshot,
        our_item_id=mla,
        sellers_excluidos=view.sellers_excluidos,
    )
    our = our_price_ars if our_price_ars is not None else _our_price_ars_from_snapshot(snapshot, mla)
    oportunidad = monopolio_c6_oportunidad(
        c6_activo=view.c6_activo,
        our_price_ars=our,
        segundo_precio_ars=segundo,
        c6_gap_min=view.c6_gap_min,
        c6_distancia_objetivo=view.c6_distancia_objetivo,
    )
    if oportunidad is None:
        return None
    return MonopolioEvaluacion(
        oportunidad=oportunidad,
        # Stable presence marker (not live precio_objetivo) so PM discard survives rival $1 moves.
        flag_tuple=(C6_FINGERPRINT_KEY, 1.0),
        solo_via_promo=bool(view.c6_solo_via_promo),
    )


def pick_mejor_candidata_auto(candidatas: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """R-AUTO pick: classic → C2 → C6 raise-assist (``path_c6``); best markup in the chosen pool."""
    ranked = [c for c in candidatas if c.get("markup") is not None]
    # Fingerprint-only C6 rows are not enrollable; raise-assist promos use path_c6 + real promo key.
    enrollable = [c for c in ranked if c.get("key") != C6_FINGERPRINT_KEY]
    classic = [c for c in enrollable if c.get("path_clasico")]
    c2 = [c for c in enrollable if c.get("path_c2")]
    c6_assist = [c for c in enrollable if c.get("path_c6")]
    if classic:
        pool: List[Dict[str, Any]] = list(classic)
    elif c2:
        pool = list(c2)
    elif c6_assist:
        pool = list(c6_assist)
    else:
        return None
    use_sio = all(c.get("markup_sell_in_out") is not None for c in pool)
    best = pool[0]
    for candidata in pool[1:]:
        best_m = best.get("markup_sell_in_out") if use_sio else best.get("markup")
        cand_m = candidata.get("markup_sell_in_out") if use_sio else candidata.get("markup")
        if cand_m is not None and best_m is not None and float(cand_m) > float(best_m):
            best = candidata
    return dict(best)


def resolve_auto_enroll_target(
    candidatas: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Map the Auto pick to enroll kwargs. None when nothing enrollable (e.g. LIGHTNING without stock)."""
    picked = pick_mejor_candidata_auto(candidatas)
    if picked is None:
        return None
    entry = next((e for e in candidates if promotion_key(e) == picked["key"]), None)
    if entry is None:
        return None
    promo_id = entry.get("id")
    promo_type = entry.get("type") or entry.get("promotion_type")
    if promo_id is None or not promo_type:
        return None
    promo_type_s = str(promo_type)
    stock_min: Optional[int] = None
    if promo_type_s == "LIGHTNING":
        stock = entry.get("stock") if isinstance(entry.get("stock"), Mapping) else None
        if not isinstance(stock, Mapping) or not isinstance(stock.get("min"), int):
            return None
        stock_min = int(stock["min"])
    return {
        "promotion_id": str(promo_id),
        "promotion_type": promo_type_s,
        "deal_price": float(picked["price"]),
        "precio_visto": float(picked["price"]),
        "markup_visto": picked.get("markup"),
        "stock": stock_min,
        "key": picked["key"],
    }


def _try_auto_enroll(item_id: str, target: Mapping[str, Any]) -> Dict[str, Any]:
    """Call enroll outside the flag savepoint. Never raises."""
    try:
        from app.services.ml_promotions_write_service import enroll_one_item

        return enroll_one_item(
            item_id,
            str(target["promotion_id"]),
            str(target["promotion_type"]),
            deal_price=target.get("deal_price"),
            precio_visto=target.get("precio_visto"),
            markup_visto=target.get("markup_visto"),
            stock=target.get("stock"),
            auto_aplicacion=True,
        )
    except Exception as exc:
        logger.warning("hay_mejores R-AUTO enroll failed for %s: %s", item_id, exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


def _auto_enroll_succeeded(outcome: Mapping[str, Any]) -> bool:
    # Only definitive applies clear the pending marker. ``ambiguous`` stays pending (no re-flag,
    # no second enroll on the next recompute of the same pick).
    return outcome.get("status") in {"submitted", "reconciled_applied"}


def _auto_enroll_is_ambiguous(outcome: Mapping[str, Any]) -> bool:
    return outcome.get("status") == "ambiguous"


def _auto_enroll_fail_reason(outcome: Mapping[str, Any]) -> str:
    """Human reason from enroll_one_item (``detail``) or exception path (``error``)."""
    for key in ("detail", "error", "message", "status"):
        value = outcome.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "enroll rechazado"


AUTO_PENDING_PREFIX = "auto_pending:"
# Ambiguous MeLi outcomes leave a pending marker; expire so a better pick can enroll later.
AUTO_PENDING_TTL_SECONDS = 30 * 60


def _auto_pending_fingerprint(pick_key: str, *, now: Optional[datetime] = None) -> str:
    """``auto_pending:{key}:{unix}`` — key may contain ``:``; timestamp is the last ``:`` segment."""
    instant = now if now is not None else datetime.now(timezone.utc)
    return f"{AUTO_PENDING_PREFIX}{pick_key}:{int(instant.timestamp())}"


def _parse_auto_pending(fingerprint: Optional[str]) -> Optional[Tuple[str, Optional[int]]]:
    """Return ``(pick_key, unix_ts_or_None)`` for pending fingerprints; None if not pending."""
    if not fingerprint or not str(fingerprint).startswith(AUTO_PENDING_PREFIX):
        return None
    rest = str(fingerprint)[len(AUTO_PENDING_PREFIX) :]
    if not rest:
        return None
    key, sep, ts_s = rest.rpartition(":")
    if not sep:
        # Legacy ``auto_pending:{key}`` without timestamp — treat as expired (no TTL).
        return (rest, None)
    try:
        return (key, int(ts_s))
    except ValueError:
        return (rest, None)


def _is_auto_pending_fingerprint(
    fingerprint: Optional[str],
    pick_key: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
    ttl_seconds: int = AUTO_PENDING_TTL_SECONDS,
) -> bool:
    """True when fingerprint is an in-flight Auto pending for ``pick_key`` (or any key) and not expired.

    Without ``pick_key``, any non-expired pending matches (legacy callers). With ``pick_key``, only
    that promo is blocked — a different candidata may enroll.
    """
    parsed = _parse_auto_pending(fingerprint)
    if parsed is None:
        return False
    pending_key, unix_ts = parsed
    if pick_key is not None and pending_key != str(pick_key):
        return False
    if unix_ts is None:
        return False  # legacy / unparseable → expired
    instant = now if now is not None else datetime.now(timezone.utc)
    age = int(instant.timestamp()) - int(unix_ts)
    return 0 <= age <= int(ttl_seconds)


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
    auto_target: Optional[Dict[str, Any]] = None
    try:
        with db.begin_nested():
            # Lock the promotions row so concurrent sync+worker cannot double-enroll Auto.
            row = (
                db.query(MlItemSellerPromotions)
                .filter(MlItemSellerPromotions.item_id == item_id)
                .with_for_update()
                .one_or_none()
            )
            if row is None:
                return None
            prev_flag = bool(row.hay_mejores_ofertas)
            prev_fingerprint = row.hay_mejores_fingerprint
            # getattr: unit stubs may omit the column; default participate (False).
            if bool(getattr(row, "hay_mejores_excluido", False)):
                decision = decidir_flag_hay_mejores(mejores=[], descartado_fingerprint=None)
                row.hay_mejores_ofertas = False
                row.hay_mejores_fingerprint = None
                row.hay_mejores_descartado_fingerprint = None
            else:
                sale = db.query(MlItemSalePrice).filter(MlItemSalePrice.item_id == item_id).one_or_none()
                baseline = float(sale.amount) if sale is not None and sale.amount is not None else None
                raw = raw_promotions if raw_promotions is not None else row.raw
                now_instant = now if now is not None else datetime.now(timezone.utc)
                candidates = _candidate_entries(raw, now_instant)
                evaluacion: Optional[MejoresEvaluacion] = None
                mejores: List[MejorTuple] = []
                criterios_view = get_criterios(db, item_id)
                if baseline is not None and baseline > 0 and candidates:
                    evaluacion = evaluar_mejores_candidatas(
                        db,
                        item_id,
                        candidates,
                        baseline,
                        raw_promotions=raw,
                        sell_in_out_batch=sell_in_out_batch,
                    )
                    mejores = list(evaluacion.mejores)
                monopolio = evaluar_monopolio_c6(db, item_id, criterios=criterios_view, our_price_ars=baseline)
                # solo_via_promo: synthetic c6:1 stays UI-only; path_c6 assist promos still flag.
                # When off, C6 alone can flag (Premium editable / no promo assist required).
                if monopolio is not None and not monopolio.solo_via_promo:
                    mejores = [*mejores, monopolio.flag_tuple]
                decision = decidir_flag_hay_mejores(
                    mejores=mejores,
                    descartado_fingerprint=row.hay_mejores_descartado_fingerprint,
                )
                if (
                    decision.hay_mejores
                    and (not prev_flag or prev_fingerprint != decision.fingerprint)
                    and criterios_view.auto_aplicacion
                    and evaluacion is not None
                    and evaluacion.candidatas
                ):
                    auto_target = resolve_auto_enroll_target(evaluacion.candidatas, candidates)

                pick_key = str(auto_target.get("key") or "") if auto_target else None
                # Same-promo pending (non-expired) blocks re-queue; other picks / expired may proceed.
                pending_blocks_pick = bool(
                    pick_key and _is_auto_pending_fingerprint(prev_fingerprint, pick_key, now=now_instant)
                )
                pending_any_alive = _is_auto_pending_fingerprint(prev_fingerprint, now=now_instant)
                would_transition = bool(
                    decision.hay_mejores
                    and (not prev_flag or prev_fingerprint != decision.fingerprint)
                    and not pending_blocks_pick
                )
                if auto_target is not None and would_transition:
                    # R-AUTO: hide flag; keep auto_pending fingerprint so ambiguous does not re-enroll.
                    pending_fp = _auto_pending_fingerprint(
                        str(auto_target.get("key") or decision.fingerprint or ""),
                        now=now_instant,
                    )
                    row.hay_mejores_ofertas = False
                    row.hay_mejores_fingerprint = pending_fp
                    row.hay_mejores_descartado_fingerprint = None
                    record_flag_transition(
                        db,
                        item_id,
                        payload={
                            "fingerprint": decision.fingerprint,
                            "prev_flag": prev_flag,
                            "prev_fingerprint": prev_fingerprint,
                            "status_quo": evaluacion.status_quo if evaluacion else {},
                            "candidatas": evaluacion.candidatas if evaluacion else [],
                            "criterios": (
                                evaluacion.criterios if evaluacion else _criterios_audit_dict(criterios_view)
                            ),
                            "monopolio": monopolio.oportunidad if monopolio else None,
                            "auto_aplicacion": True,
                            "auto_pick": auto_target.get("key"),
                            "auto_deferred": True,
                            "auto_pending_fingerprint": pending_fp,
                        },
                    )
                elif pending_blocks_pick or (pending_any_alive and auto_target is None):
                    # Keep inflight pending; do not surface the manual flag yet.
                    row.hay_mejores_ofertas = False
                    row.hay_mejores_fingerprint = prev_fingerprint
                    auto_target = None
                else:
                    auto_target = None  # manual / non-Auto path — do not schedule enroll
                    row.hay_mejores_ofertas = decision.hay_mejores
                    row.hay_mejores_fingerprint = decision.fingerprint
                    row.hay_mejores_descartado_fingerprint = decision.descartado_fingerprint
                    if would_transition:
                        _enqueue_catalog_competition_refresh(db, item_id)
                        record_flag_transition(
                            db,
                            item_id,
                            payload={
                                "fingerprint": decision.fingerprint,
                                "prev_flag": prev_flag,
                                "prev_fingerprint": prev_fingerprint,
                                "status_quo": evaluacion.status_quo if evaluacion else {},
                                "candidatas": evaluacion.candidatas if evaluacion else [],
                                "criterios": (
                                    evaluacion.criterios if evaluacion else _criterios_audit_dict(criterios_view)
                                ),
                                "monopolio": monopolio.oportunidad if monopolio else None,
                                "auto_aplicacion": bool(criterios_view.auto_aplicacion),
                            },
                        )
        if auto_target is not None:
            _schedule_auto_enroll(db, item_id, auto_target, decision)
            if prev_flag:
                notify_hay_mejores_changed(db)
            return FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
        if decision.hay_mejores != prev_flag:  # after the savepoint: a failed one changed nothing
            notify_hay_mejores_changed(db)
        return decision
    except Exception as exc:
        logger.warning("hay_mejores: failed for %s: %s", item_id, exc, exc_info=True)
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
    from app.services.ml_catalog_competition_service import prefetch_catalog_snapshots
    from app.services.ml_hay_mejores_criterios_service import prefetch_criterios

    batch = resolver_sell_in_out_para_mlas(db, ids)
    prefetch_criterios(db, ids)
    prefetch_catalog_snapshots(db, ids)
    for item_id in ids:
        rows[item_id].hay_mejores_excluido = False
        actualizar_hay_mejores_ofertas(db, item_id, sell_in_out_batch=batch)
    return ids


_CATALOG_REFRESH_ENQUEUED = "hay_mejores_catalog_refresh_enqueued"


def _enqueue_catalog_competition_refresh(db: Session, item_id: str) -> None:
    """Best-effort enqueue of the catalog MLA to refresh; never undoes hay_mejores.

    Runs in its own SAVEPOINT so a failed INSERT (missing table, lock, etc.)
    cannot abort the outer hay_mejores nested transaction.

    Within one Session/run, the same MLA is enqueued at most once (stale/missing
    snapshot on every evaluate must not reset the pending row each pass).
    """
    try:
        from datetime import UTC, datetime

        from app.services.catalog_competition_refresh_queue import enqueue
        from app.services.catalog_competition_target import mla_for_catalog_competition_refresh

        info = getattr(db, "info", None)
        already = info.setdefault(_CATALOG_REFRESH_ENQUEUED, set()) if isinstance(info, dict) else None
        with db.begin_nested():
            target = mla_for_catalog_competition_refresh(db, item_id)
            if target is None:
                return
            if already is not None and target in already:
                return
            enqueue(db, [target], datetime.now(UTC))
            if already is not None:
                already.add(target)
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


def descartar_hay_mejores_sugerencias_bulk(
    db: Session,
    item_ids: Sequence[str],
    *,
    skip_auto_fail: bool = True,
) -> Tuple[List[str], List[str]]:
    """Clear open hay_mejores flags for many MLAs.

    Returns ``(descartadas, omitidas_auto_fail)``. When ``skip_auto_fail`` is true, suggestions whose
    latest audit is an R-AUTO enroll failure stay open (owner: bulk discard must not clear them).
    """
    from app.services.ml_hay_mejores_audit_service import latest_auto_fail_message

    ids = [item_id for item_id in dict.fromkeys(item_ids) if item_id]
    if not ids:
        return [], []
    rows = {
        row.item_id: row
        for row in db.query(MlItemSellerPromotions)
        .filter(MlItemSellerPromotions.item_id.in_(ids), MlItemSellerPromotions.hay_mejores_ofertas.is_(True))
        .all()
    }
    descartadas: List[str] = []
    omitidas: List[str] = []
    for item_id in ids:
        row = rows.get(item_id)
        if row is None:
            continue
        if skip_auto_fail and latest_auto_fail_message(db, item_id):
            omitidas.append(item_id)
            continue
        row.hay_mejores_ofertas = False
        if row.hay_mejores_fingerprint:
            row.hay_mejores_descartado_fingerprint = row.hay_mejores_fingerprint
        descartadas.append(item_id)
    if descartadas:
        notify_hay_mejores_changed(db)
    return descartadas, omitidas


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
