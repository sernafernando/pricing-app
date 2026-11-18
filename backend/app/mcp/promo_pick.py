"""Port of the panel's Sugerida pick (frontend `pickPonerPreciosPromos.js`, main 6cc67d2a8) for the MCP (L9).

Same rules, same names: the status quo (`baseline_promo`), the per-type suggestions among the candidates applicable
now that beat it (`pick_mejores_candidatas`), plus the L9 choice the panel leaves to the operator: `best_suggestion`
(the suggestion with the highest markup with sell in) and its `improvement` over the status quo.
Both sides run `tests/fixtures/pick_mejores_candidatas_cases.json`: change one, change the other.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.services.ml_promotions_aplicable import WRITABLE_PROMOTION_TYPES, candidata_aplicable_ahora, es_premium_del_mes

Promo = Mapping[str, Any]

CHOOSER_SLOT_TYPES = (
    "SMART",
    "DEAL",
    "PRE_NEGOTIATED",
    "PRICE_MATCHING",
    "LIGHTNING",
    "SMART_LIGHTNING",
    "SELLER_CAMPAIGN",
)


def finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _positive_number(value: Any) -> float | None:
    """JS `Number(value) > 0` (strings included), else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _status_text(promo: Promo) -> str | None:
    status = promo.get("status")
    value = status.get("id") if isinstance(status, Mapping) else status
    return value if isinstance(value, str) else None


def promo_name(promo: Promo | None) -> str | None:
    """`resolvePromoName`."""
    if not promo:
        return None
    payload = promo.get("payload")
    return promo.get("name") or (payload.get("name") if isinstance(payload, Mapping) else None) or None


def promo_display_price(promo: Promo | None) -> float | None:
    """`promoDisplayPrice`: the price the row shows (a LIGHTNING candidate: its suggestion clamped to ML's range)."""
    if not promo:
        return None
    promo_type = promo.get("promotion_type") or promo.get("type")
    if promo_type == "LIGHTNING" and _status_text(promo) == "candidate":
        suggested = _positive_number(promo.get("suggested_discounted_price"))
        if suggested is not None:
            low = _positive_number(promo.get("min_discounted_price"))
            high = _positive_number(promo.get("max_discounted_price"))
            if high is not None:
                suggested = min(suggested, high)
            if low is not None:
                suggested = max(suggested, low)
            return suggested
    price = _positive_number(promo.get("price"))
    if price is not None:
        return price
    if promo_type == "DEAL":
        high = _positive_number(promo.get("max_discounted_price"))
        if high is not None:
            return high
    return _positive_number(promo.get("suggested_discounted_price"))


def baseline_promo(promotions: Iterable[Promo] | None) -> Promo | None:
    """`baselinePromo`: the started offer ML applies now (Activa ahora), None when none qualifies."""
    started = [p for p in (promotions or []) if p and p.get("status") == "started"]
    derived = any("application_status" in p for p in started)
    pool = [p for p in started if p.get("application_status") == "active"]
    if not pool and not derived:
        prices = [price for p in started if (price := promo_display_price(p)) is not None]
        min_price = min(prices) if prices else None
        pool = (
            started
            if min_price is None
            else [p for p in started if promo_display_price(p) is None or promo_display_price(p) == min_price]
        )
    usable = [
        p for p in pool if finite_or_none(p.get("nuestro_markup")) is not None and promo_display_price(p) is not None
    ]
    best: Promo | None = None
    for promo in usable:
        if best is None or promo["nuestro_markup"] > best["nuestro_markup"]:
            best = promo
    return best


def comparable_markups(candidate: Promo, baseline: Promo) -> tuple[float | None, float | None]:
    """`comparableMarkups`: with sell in / sell out only when both sides have it, else both plain."""
    candidate_sio = finite_or_none(candidate.get("markup_sell_in_out"))
    baseline_sio = finite_or_none(baseline.get("markup_sell_in_out"))
    candidate_plain = finite_or_none(candidate.get("nuestro_markup"))
    baseline_plain = finite_or_none(baseline.get("nuestro_markup"))
    if None not in (candidate_plain, baseline_plain, candidate_sio, baseline_sio):
        return candidate_sio, baseline_sio
    return candidate_plain, baseline_plain


def es_mejor_oferta(
    candidate_price: float | None,
    candidate_markup: float | None,
    baseline_price: float | None,
    baseline_markup: float | None,
) -> bool:
    """`esMejorOferta`: markup up at the same price; markup kept or up at a lower price; never a higher price."""
    values = (candidate_price, candidate_markup, baseline_price, baseline_markup)
    if any(finite_or_none(v) is None for v in values):
        return False
    if candidate_price > baseline_price:
        return False
    if candidate_price == baseline_price:
        return candidate_markup > baseline_markup
    return candidate_markup >= baseline_markup


def best_by_markup(promos: Iterable[Promo]) -> Promo | None:
    """`bestByMarkup`: one basis for the whole set (with sell in only when every candidate has it)."""
    ranked = [p for p in promos if finite_or_none(p.get("nuestro_markup")) is not None]
    key = (
        "markup_sell_in_out"
        if all(finite_or_none(p.get("markup_sell_in_out")) is not None for p in ranked)
        else "nuestro_markup"
    )
    best: Promo | None = None
    for promo in ranked:
        if best is None or promo[key] > best[key]:
            best = promo
    return best


def _lightning_has_stock_range(promo: Promo) -> bool:
    payload = promo.get("payload")
    stock = payload.get("stock") if isinstance(payload, Mapping) else None
    if not isinstance(stock, Mapping):
        return False
    return all(
        not isinstance(v, bool) and isinstance(v, (int, float)) and float(v).is_integer()
        for v in (stock.get("min"), stock.get("max"))
    )


def _matches_chooser_slot(promo: Promo, promo_type: str, now: datetime) -> bool:
    if promo.get("promotion_type") != promo_type:
        return False
    if promo_type == "SELLER_CAMPAIGN":
        return es_premium_del_mes(promo_name(promo), now)
    if promo_type == "LIGHTNING":
        return _lightning_has_stock_range(promo)
    return True


def _applicable_now(promo: Promo, now: datetime) -> bool:
    """`isApplicableNow` (the backend `candidata_aplicable_ahora`, which runs the same shared cases)."""
    entry = {
        "type": promo.get("promotion_type"),
        "start_date": promo.get("start_date"),
        "finish_date": promo.get("finish_date"),
        "name": promo_name(promo),
    }
    return candidata_aplicable_ahora(entry, now)


def pick_slots(candidates: list[Promo], now: datetime) -> dict[str, Promo | None]:
    """`pickSlots`: one best-by-markup promo per chooser type that is writable today."""
    picked: dict[str, Promo | None] = {}
    for promo_type in CHOOSER_SLOT_TYPES:
        if promo_type not in WRITABLE_PROMOTION_TYPES:
            picked[promo_type] = None
            continue
        picked[promo_type] = best_by_markup([p for p in candidates if _matches_chooser_slot(p, promo_type, now)])
    return picked


def pick_mejores_candidatas(
    promotions: Iterable[Promo] | None,
    *,
    baseline_price: float | None,
    baseline_markup: float | None,
    baseline_sell_in_out: float | None,
    now: datetime,
) -> dict[str, Promo | None]:
    """`pickMejoresCandidatas`: the Sugeridas, per type, among candidates applicable now that beat the status quo."""
    baseline = {"nuestro_markup": baseline_markup, "markup_sell_in_out": baseline_sell_in_out}
    candidates = [p for p in (promotions or []) if p and p.get("status") == "candidate" and _applicable_now(p, now)]
    better = []
    for promo in candidates:
        candidate_markup, status_quo_markup = comparable_markups(promo, baseline)
        if es_mejor_oferta(promo_display_price(promo), candidate_markup, baseline_price, status_quo_markup):
            better.append(promo)
    return pick_slots(better, now)


def best_suggestion(slots: Mapping[str, Promo | None]) -> Promo | None:
    """L9 option A: the suggestion with the highest markup with sell in (plain markup when one lacks it, as
    `bestByMarkup`); a tie goes to the lower price."""
    picked = [p for p in slots.values() if p]
    ranked = [p for p in picked if finite_or_none(p.get("nuestro_markup")) is not None]
    key = (
        "markup_sell_in_out"
        if all(finite_or_none(p.get("markup_sell_in_out")) is not None for p in ranked)
        else "nuestro_markup"
    )
    best: Promo | None = None
    for promo in ranked:
        if best is None or promo[key] > best[key]:
            best = promo
        elif promo[key] == best[key] and (promo_display_price(promo) or math.inf) < (
            promo_display_price(best) or math.inf
        ):
            best = promo
    return best


def improvement(best: Promo | None, current: Mapping[str, Any]) -> dict[str, Any] | None:
    """Markup of `best` minus the status quo's, in points and in % of the status quo, on the comparable basis."""
    if not best:
        return None
    best_value, current_value = comparable_markups(best, current)
    if best_value is None or current_value is None:
        return None
    basis = (
        "markup_sell_in_out"
        if finite_or_none(best.get("markup_sell_in_out")) is not None
        and finite_or_none(current.get("markup_sell_in_out")) is not None
        and finite_or_none(best.get("nuestro_markup")) is not None
        and finite_or_none(current.get("nuestro_markup")) is not None
        else "nuestro_markup"
    )
    points = round(best_value - current_value, 2)
    percent = round(points / abs(current_value) * 100, 2) if current_value else None
    return {"points": points, "percent": percent, "basis": basis}
