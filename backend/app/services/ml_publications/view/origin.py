"""Who caused an event of the Eventos tab or an entry of the Historial tab (eventos-historial-legibles T3).

`kind` is one of:

- `nosotros`: one of OUR audit rows explains it (same MLA, same target when there is one, written within
  `ORIGIN_WINDOW` before ML's change was observed) and the row names a user: `user_name` is that user's name.
- `automatico`: the matching audit row has no user (a system or worker write), or the change is to our own link
  table and the SKU rule made it (see `_link_fallback`).
- `ml`: ML makes this change by nature (an offer, the catalog competition, a moderation, the visits).
- `sin_registrar`: it could be ours or ML's and no audit row of ours explains it. NEVER `nosotros` without a row.

`informational` marks what ML offered or suggested without anything applied changing (an offer, a candidate no
longer offered, suggested prices, metrics).

The audit trails read are every place that records a write of ours to ML: `ml_write_log` (promotion enroll and
remove), `auditoria` (PxQ prices `PXQ_PRECIO_PUBLICADO`, manual links `ML_VINCULO_*`; `item_id` there is the ERP
product, the MLA travels in `valores_nuevos.mla`, `fecha` is naive UTC) and `free_shipping_fix_log` (the free
shipping fix; it stores no user). `load_audits` reads them for one MLA and one time range in ONE statement, whatever
the page holds; `of_event`/`of_entry` then decide in memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.auditoria import TipoAccion
from app.models.ml_write_log import ACTION_ENROLL, ACTION_REMOVE, RESOURCE_PROMOTION

# How long after one of our writes ML's change may be observed and still be ours. A write we make to ML is seen by
# the store when the `items` notification it triggers is fetched: measured on production (2026-10-17, last 2 days,
# `ml_items.fetched_at - last_trigger_received_at`) p50 43 s, p95 9 min, p99 12 min; the promotions sub-resource
# is fetched at most every 300 s (`ML_PUB_MIN_AGE_SECONDS["promotions"]`) on top of that. 30 minutes covers the
# p99 plus one promotions minimum age with margin. A change seen later (a missed notification recovered by
# `/missed_feeds` or a sweep, hours later) is left `sin_registrar`: a wider window would start crediting us with
# ML's own changes, and an honest "unregistered" is better than a wrong "ours".
ORIGIN_WINDOW = timedelta(minutes=30)

NOSOTROS, AUTOMATICO, ML, SIN_REGISTRAR = "nosotros", "automatico", "ml", "sin_registrar"
KINDS = (NOSOTROS, AUTOMATICO, ML, SIN_REGISTRAR)

# Audit sources: one per kind of write of ours.
SOURCE_PROMOTION, SOURCE_PXQ, SOURCE_LINK, SOURCE_FREE_SHIPPING = "promotion", "pxq", "link", "free_shipping"
LINK_ACTIONS = (TipoAccion.ML_VINCULO_MANUAL, TipoAccion.ML_VINCULO_SIN_PRODUCTO, TipoAccion.ML_VINCULO_AUTOMATICO)
SKU_RULE_SOURCE = "sku_auto"  # `ml_item_product_links.source` of a link the SKU rule set


@dataclass(frozen=True)
class Audit:
    """One audit row of ours. `target_id` is the promotion id (promotions) or the variation id (links)."""

    source: str
    created_at: datetime
    action: Optional[str] = None
    target_id: Optional[str] = None
    user_name: Optional[str] = None
    has_user: bool = False


@dataclass(frozen=True)
class Verdict:
    kind: str
    user_name: Optional[str] = None
    informational: bool = False

    def origin(self) -> dict[str, Any]:
        return {"kind": self.kind, "user_name": self.user_name}


@dataclass(frozen=True)
class Claim:
    """The audit rows that could explain a change seen at `at`: of these sources and actions, and of one of these
    targets (`None`: any target, the change carries none to compare)."""

    at: datetime
    sources: frozenset[str]
    actions: Optional[frozenset[str]] = None
    targets: Optional[frozenset[str]] = None


@dataclass(frozen=True)
class EventRule:
    """`fallback` is the kind when no audit row matches; `sources` empty means the type is never matched."""

    fallback: str
    informational: bool = False
    sources: frozenset[str] = frozenset()
    actions: Optional[frozenset[str]] = None
    by_promotion: bool = False  # the event's `promotion_id` must be the audit row's target


_PROMOTION = frozenset({SOURCE_PROMOTION})
_UNREGISTERED = EventRule(SIN_REGISTRAR)
_BY_ML = EventRule(ML)

# Every type of `events.EVENT_TYPES`, classified explicitly (a test fails when a new type is missing here).
EVENT_RULES: dict[str, EventRule] = {
    # We may pause, activate or close a publication and ML does too; we keep no audit of those writes.
    "status_paused": _UNREGISTERED,
    "status_activated": _UNREGISTERED,
    "status_closed": _UNREGISTERED,
    "status_changed_other": _UNREGISTERED,
    "status_under_review": _BY_ML,  # ML's review
    "sub_status_changed": _BY_ML,  # ML derives the sub-status (out of stock, warning, ...)
    # Sales and the ERP stock sync move the stock; no audit row of ours.
    "stock_depleted": _UNREGISTERED,
    "stock_replenished": _UNREGISTERED,
    # A promotion or sale price moves when we enroll or remove a promotion (see `event_claim`).
    "price_changed": EventRule(SIN_REGISTRAR, sources=_PROMOTION),
    "promotion_offered": EventRule(ML, informational=True),
    "promotion_activated": EventRule(
        SIN_REGISTRAR, sources=_PROMOTION, actions=frozenset({ACTION_ENROLL}), by_promotion=True
    ),
    # A candidate no longer offered is ML's (see `_finished_fallback`).
    "promotion_finished": EventRule(
        SIN_REGISTRAR, sources=_PROMOTION, actions=frozenset({ACTION_REMOVE}), by_promotion=True
    ),
    "promotion_price_changed": EventRule(
        SIN_REGISTRAR, sources=_PROMOTION, actions=frozenset({ACTION_ENROLL}), by_promotion=True
    ),
    "catalog_competition_won": _BY_ML,
    "catalog_competition_lost": _BY_ML,
    "moderation_applied": _BY_ML,
    "moderation_resolved": _BY_ML,
    # Our own link table: an operator decision is audited, the SKU rule is automatic (see `_link_fallback`).
    "product_link_changed": EventRule(SIN_REGISTRAR, sources=frozenset({SOURCE_LINK})),
    "item_gone": _UNREGISTERED,
    "item_restored": _UNREGISTERED,
    "listing_type_changed": _UNREGISTERED,
    "title_changed": _UNREGISTERED,
}

# History entries by resource. `promotions`, `prices`/`sale_price`, `product_link` and `item` are matched against
# audit rows (`entry_claim`); the rest are ML's by nature or unregistered.
RESOURCE_FALLBACKS: dict[str, Verdict] = {
    "competition": Verdict(ML),
    "moderation": Verdict(ML),
    "performance": Verdict(ML, informational=True),
    "visits": Verdict(ML, informational=True),
    "replenishment": Verdict(ML, informational=True),  # ML's restock suggestion
}
PRICE_RESOURCES = ("prices", "sale_price")
PRICE_KINDS_OF_PROMOTIONS = ("promotion", "sale")
APPLIED_PROMOTION_STATES = ("started", "pending")

_PROMOTION_KEY = re.compile(r"^\[([^\]]+)\]")


def _variation_target(value: Any) -> Optional[frozenset[str]]:
    return None if value is None or value == "" else frozenset({str(value)})


# ── Events ────────────────────────────────────────────────────────────────────────────────────────────────────


def event_claim(event: Mapping[str, Any]) -> Optional[Claim]:
    rule = EVENT_RULES.get(event["event_type"])
    if rule is None or not rule.sources:
        return None
    if event["event_type"] == "price_changed":
        if event.get("price_kind") not in PRICE_KINDS_OF_PROMOTIONS:
            return None  # the standard price: no write of ours is audited for it
        return Claim(event["observed_at"], rule.sources)  # the sale price's id is the offer's, not the campaign's
    targets = None
    if rule.by_promotion and event.get("promotion_id"):
        targets = frozenset({event["promotion_id"]})
    elif SOURCE_LINK in rule.sources:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        targets = _variation_target(payload.get("variation_id"))
    return Claim(event["observed_at"], rule.sources, rule.actions, targets)


def _event_fallback(event: Mapping[str, Any]) -> Verdict:
    rule = EVENT_RULES.get(event["event_type"], _UNREGISTERED)
    if event["event_type"] == "promotion_finished" and event.get("old_value") == "candidate":
        return Verdict(ML, informational=True)  # an offer ML took back: nothing applied changed
    if event["event_type"] == "product_link_changed":
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        return _link_fallback(payload.get("source_new"), payload.get("linked_by"))
    return Verdict(rule.fallback, informational=rule.informational)


def of_event(event: Mapping[str, Any], audits: Sequence[Audit]) -> Verdict:
    return _resolve(event_claim(event), audits) or _event_fallback(event)


# ── History entries ───────────────────────────────────────────────────────────────────────────────────────────


def _link_fallback(source: Any, linked_by: Any = None) -> Verdict:
    """Every operator decision on a link writes its `auditoria` row in the link change's own transaction
    (`links._record_audit`), so a change with no row that the SKU rule made, with no author, is the link worker's."""
    if source == SKU_RULE_SOURCE and linked_by is None:
        return Verdict(AUTOMATICO)
    return Verdict(SIN_REGISTRAR)


def _status(value: Any) -> Any:
    return value.get("status") if isinstance(value, dict) else value


def _touches_applied_promotion(changes: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a promotions row changed something applied: an entry added or removed while started/pending, a status
    to or from those, or a price (only an enrolled promotion has one). Suggested prices and candidates do not."""
    for change in changes:
        path = str(change.get("p", ""))
        match = _PROMOTION_KEY.match(path)
        if match is None:
            continue
        rest = path[match.end() :]
        if rest in ("", ".status"):
            states = (_status(change.get("old")), _status(change.get("new")))
            if any(state in APPLIED_PROMOTION_STATES for state in states):
                return True
        elif rest == ".price":
            return True
    return False


def _only_our_free_shipping_fix(changes: Sequence[Mapping[str, Any]]) -> bool:
    """An item row that turned free shipping OFF (what the fix does) and changed no business field; a row that also
    moved a price or a status is not credited to the fix."""
    from app.services.ml_publications.view.history import split  # the history module imports this one

    turned_off = any(c.get("p") == "shipping.free_shipping" and c.get("new") is False for c in changes)
    business, _ = split("item", changes)
    return turned_off and not business


def entry_claim(entry: Mapping[str, Any]) -> Optional[Claim]:
    resource, changes, at = entry["resource_type"], entry.get("changes") or [], entry["observed_at"]
    if resource == "promotions":
        targets = {m.group(1) for c in changes if (m := _PROMOTION_KEY.match(str(c.get("p", ""))))}
        return Claim(at, _PROMOTION, targets=frozenset(targets)) if targets else None
    if resource in PRICE_RESOURCES:
        return Claim(at, frozenset({SOURCE_PROMOTION, SOURCE_PXQ}))
    if resource == "product_link":
        _, _, variation = str(entry.get("entity_id") or "").partition(":")
        return Claim(at, frozenset({SOURCE_LINK}), targets=_variation_target(variation))
    if resource == "item" and _only_our_free_shipping_fix(changes):
        return Claim(at, frozenset({SOURCE_FREE_SHIPPING}))
    return None


def _entry_fallback(entry: Mapping[str, Any]) -> Verdict:
    resource = entry["resource_type"]
    if resource == "promotions":
        if _touches_applied_promotion(entry.get("changes") or []):
            return Verdict(SIN_REGISTRAR)
        return Verdict(ML, informational=True)
    if resource == "product_link":
        return _link_fallback(entry.get("link_source"))
    return RESOURCE_FALLBACKS.get(resource, Verdict(SIN_REGISTRAR))


def of_entry(entry: Mapping[str, Any], audits: Sequence[Audit]) -> Verdict:
    return _resolve(entry_claim(entry), audits) or _entry_fallback(entry)


# ── Matching and the read ─────────────────────────────────────────────────────────────────────────────────────


def _resolve(claim: Optional[Claim], audits: Sequence[Audit]) -> Optional[Verdict]:
    """The latest audit row the claim admits, as a verdict; `None` when none does."""
    if claim is None or not audits:
        return None
    earliest = claim.at - ORIGIN_WINDOW
    best: Optional[Audit] = None
    for audit in audits:
        if (
            audit.source in claim.sources
            and earliest <= audit.created_at <= claim.at
            and (claim.actions is None or audit.action in claim.actions)
            and (claim.targets is None or audit.target_id in claim.targets)
            and (best is None or audit.created_at > best.created_at)
        ):
            best = audit
    if best is None:
        return None
    return Verdict(NOSOTROS, best.user_name) if best.has_user else Verdict(AUTOMATICO)


def span(claims: Iterable[Optional[Claim]]) -> Optional[tuple[datetime, datetime]]:
    """The time range the audit rows of these claims can lie in; `None` when no claim needs a read."""
    moments = [claim.at for claim in claims if claim is not None]
    if not moments:
        return None
    return min(moments) - ORIGIN_WINDOW, max(moments)


_AUDITS_SQL = text(
    "SELECT :promotion AS source, w.action, w.target_id, w.created_at, w.usuario_id, u.nombre "
    "FROM ml_write_log w LEFT JOIN usuarios u ON u.id = w.usuario_id "
    "WHERE w.mla = :mla AND w.resource = :resource AND w.created_at BETWEEN :since AND :until "
    "UNION ALL "
    "SELECT CASE WHEN a.tipo_accion = :pxq_action THEN :pxq ELSE :link END, a.tipo_accion, "
    "a.valores_nuevos ->> 'variation_id', a.fecha AT TIME ZONE 'UTC', a.usuario_id, u.nombre "
    "FROM auditoria a LEFT JOIN usuarios u ON u.id = a.usuario_id "
    "WHERE a.tipo_accion IN (:pxq_action, :link_1, :link_2, :link_3) "
    "AND a.fecha BETWEEN :since_utc AND :until_utc AND a.valores_nuevos ->> 'mla' = :mla "
    "UNION ALL "
    "SELECT :free_shipping, NULL, NULL, f.created_at, NULL, NULL FROM free_shipping_fix_log f "
    "WHERE f.mla_id = :mla AND f.success AND f.created_at BETWEEN :since AND :until"
)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def load_audits(db: Session, mla: str, claims: Iterable[Optional[Claim]]) -> list[Audit]:
    """Our audit rows of `mla` in the range the claims need, in one statement; no statement when nothing can match.
    `auditoria` stores the action by enum NAME and `fecha` as naive UTC (its column and `registrar_auditoria`)."""
    window = span(claims)
    if window is None:
        return []
    since, until = window
    link_1, link_2, link_3 = (action.name for action in LINK_ACTIONS)
    rows = db.execute(
        _AUDITS_SQL,
        {
            "mla": mla,
            "since": since,
            "until": until,
            "since_utc": _naive_utc(since),
            "until_utc": _naive_utc(until),
            "promotion": SOURCE_PROMOTION,
            "resource": RESOURCE_PROMOTION,
            "pxq": SOURCE_PXQ,
            "pxq_action": TipoAccion.PXQ_PRECIO_PUBLICADO.name,
            "link": SOURCE_LINK,
            "link_1": link_1,
            "link_2": link_2,
            "link_3": link_3,
            "free_shipping": SOURCE_FREE_SHIPPING,
        },
    ).all()
    return [
        Audit(
            source=row.source,
            created_at=row.created_at,
            action=row.action,
            target_id=row.target_id,
            user_name=row.nombre,
            has_user=row.usuario_id is not None,
        )
        for row in rows
    ]
