"""How late the store is on what ML told it changed (ml-sync-pipeline S5), measured from the queue.

A notification leaves an entry with `source_received_at` and the resources it asks for. Resource R of that entry
is late when R was not checked since the notification and has been due for longer than R's target, where due is
the notification or R's last check plus its minimum age, whichever is later: the minimum age is a wait the store
chose, not a delay. Once applied the entry leaves the queue and stops counting. A parked entry keeps counting: the
store gave up on that change, so its data stays stale until someone looks.

Visits have no notification (the sweep laps them, design D17), so they are measured by the age of their last
check on active items, and only while the sweep collects them (visits never collected show in the status
report's completeness). Stock is not measured: it is the publication's available quantity, which nothing outside
the store reads (owner, 2026-10-27).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_publications import settings_store, status
from app.services.ml_publications.bundle import min_age_seconds
from app.services.ml_publications.resources import (
    BUNDLE_RESOURCE,
    COMPETITION_RESOURCE,
    CORE_RESOURCE,
    FAMILY_KIND,
    ITEM_KIND,
)

ITEMS = "items"
VISITS = "visits"


@dataclass(frozen=True)
class _Measured:
    table: str
    key: str  # key column of `table`
    entity: str  # SQL for the key value of a queue entry `q` (with its item `i`)
    kinds: tuple
    extra: str = ""


_ITEM = "q.entity_id"
MEASURED: Dict[str, _Measured] = {
    ITEMS: _Measured("ml_items", "item_id", _ITEM, (ITEM_KIND,)),
    "prices": _Measured("ml_item_prices", "item_id", _ITEM, (ITEM_KIND,)),
    "sale_price": _Measured("ml_item_sale_prices", "item_id", _ITEM, (ITEM_KIND,)),
    "promotions": _Measured("ml_item_seller_promotions", "item_id", _ITEM, (ITEM_KIND,)),
    # Competition exists only for catalog listings (bundle.is_applicable).
    COMPETITION_RESOURCE: _Measured(
        "ml_item_competition", "item_id", _ITEM, (ITEM_KIND,), "AND i.catalog_listing IS TRUE"
    ),
    "description": _Measured("ml_item_descriptions", "item_id", _ITEM, (ITEM_KIND,)),
    "family": _Measured(
        "ml_user_product_families",
        "family_id",
        f"CASE WHEN q.kind = '{FAMILY_KIND}' THEN q.entity_id ELSE i.family_id END",
        (ITEM_KIND, FAMILY_KIND),
        f"AND (q.kind = '{FAMILY_KIND}' OR i.family_id IS NOT NULL)",
    ),
}


def _late_sql(measured: _Measured) -> Any:
    return text(
        "SELECT count(DISTINCT entity) AS late, max(age) AS oldest FROM ("
        f" SELECT {measured.entity} AS entity,"
        " CAST(extract(epoch FROM now() - GREATEST(q.source_received_at,"
        "   s.last_checked_at + make_interval(secs => :min_age))) AS double precision) AS age"
        " FROM ml_pub_refresh_queue q"
        " LEFT JOIN ml_items i ON q.kind = :item_kind AND i.item_id = q.entity_id"
        f" LEFT JOIN {measured.table} s ON s.{measured.key} = {measured.entity}"
        " WHERE q.source_received_at IS NOT NULL AND q.kind = ANY(CAST(:kinds AS text[]))"
        "  AND q.resources && CAST(:asked AS text[])"
        f"  AND (s.last_checked_at IS NULL OR s.last_checked_at < q.source_received_at) {measured.extra}"
        ") x WHERE age > :target"
    )


_VISITS_SQL = text(
    "SELECT count(*) AS late, max(age) AS oldest FROM ("
    " SELECT CAST(extract(epoch FROM now() - v.last_checked_at) AS double precision) AS age"
    " FROM ml_items i JOIN ml_item_visits v ON v.item_id = i.item_id"
    " WHERE i.status = 'active' AND i.gone_at IS NULL"
    ") x WHERE age > :target"
)


def _number(value: Any) -> Any:
    return None if value is None else float(value)


def measure(db: Session) -> Dict[str, Any]:
    """Per measured resource: its target, how many entries (items, for visits) are late and the oldest delay;
    plus the waiting count and oldest wait of each queue lane. Read-only, under the status report's timeout."""
    status.bounded_read_only(db)
    config = settings_store.get_settings(["bundle_resources", "min_age_seconds", "sweep.enabled"])
    collected: List[str] = config["bundle_resources"].value
    min_ages: Mapping[str, Any] = config["min_age_seconds"].value
    targets: Mapping[str, int] = settings.ML_PUB_FRESHNESS_TARGET_SECONDS
    resources: Dict[str, Dict[str, Any]] = {}
    for name, measured in MEASURED.items():
        if name != ITEMS and name not in collected:
            continue
        asked = [BUNDLE_RESOURCE, CORE_RESOURCE] if name == ITEMS else [BUNDLE_RESOURCE, name]
        row = db.execute(
            _late_sql(measured),
            {
                "min_age": 0 if name == ITEMS else min_age_seconds(name, min_ages),
                "item_kind": ITEM_KIND,
                "kinds": list(measured.kinds),
                "asked": asked,
                "target": targets[name],
            },
        ).one()
        resources[name] = {
            "target_seconds": targets[name],
            "late": row.late,
            "oldest_late_seconds": _number(row.oldest),
        }
    if VISITS in collected and config["sweep.enabled"].value is True:
        row = db.execute(_VISITS_SQL, {"target": targets[VISITS]}).one()
        resources[VISITS] = {
            "target_seconds": targets[VISITS],
            "late": row.late,
            "oldest_late_seconds": _number(row.oldest),
        }
    return {"resources": resources, "lanes": status.queue_lanes(db)}


LABELS: Dict[str, str] = {
    ITEMS: "estado de la publicación",
    "prices": "precio",
    "sale_price": "precio de venta",
    "promotions": "promociones",
    COMPETITION_RESOURCE: "competencia",
    "description": "descripción",
    "family": "familia",
    VISITS: "visitas",
}


def _duration(seconds: float) -> str:
    minutes = seconds / 60
    return f"{minutes / 60:.0f} h" if minutes >= 120 else f"{minutes:.0f} min"


def _unit(name: str, count: int) -> str:
    """What `count` counts: queue entries of families for `family`, publications for everything else."""
    if name == "family":
        return "familia" if count == 1 else "familias"
    return "publicación" if count == 1 else "publicaciones"


def late_message(report: Mapping[str, Any]) -> str:
    """The owner's WhatsApp for the late resources of `report`."""
    lines = ["Pricing: datos de ML atrasados."]
    for name, measured in report["resources"].items():
        if measured["late"]:
            count = measured["late"]
            lines.append(
                f"- {LABELS[name]}: {count} {_unit(name, count)}, "
                f"la más atrasada {_duration(measured['oldest_late_seconds'])} "
                f"(objetivo {_duration(measured['target_seconds'])})"
            )
    return "\n".join(lines)
