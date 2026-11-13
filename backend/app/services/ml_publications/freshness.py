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

import math
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
# A delay counts as late only past its target plus 5 %: "5 segundos de diferencia no es demora si el objetivo es
# dos min, tendríamos que tener un 5% de tolerancia" (owner, 2026-11-03).
LATE_TOLERANCE = 1.05


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
    "family": _Measured(
        "ml_user_product_families",
        "family_id",
        # The queue keys every entry as text; a family's id is a bigint like `ml_items.family_id`.
        f"CASE WHEN q.kind = '{FAMILY_KIND}' THEN CAST(q.entity_id AS bigint) ELSE i.family_id END",
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


# Swept resources (no notification refetches them): the age of the last check on active items. Fixed table names.
SWEPT: Dict[str, str] = {"description": "ml_item_descriptions", VISITS: "ml_item_visits"}


# Swept resources that joined the sweep recently: the age counts from their first successful sweep tick at the
# latest, so the first lap after the change gets its whole target before anything reads as late (no false alert the
# day the description moved to the sweep). Visits have been swept since the start and keep the plain age.
SWEEP_GRACE = frozenset({"description"})

_FIRST_SWEEP_TICK = text(
    "SELECT min(started_at) FROM ml_pub_job_runs WHERE job = 'sweep' AND outcome = 'success'"
    " AND (',' || scope || ',') LIKE :scope"
)


def _swept_sql(table: str, *, since_first_tick: bool) -> Any:
    checked = "GREATEST(v.last_checked_at, :first_tick)" if since_first_tick else "v.last_checked_at"
    return text(
        "SELECT count(*) AS late, max(age) AS oldest FROM ("
        f" SELECT CAST(extract(epoch FROM now() - {checked}) AS double precision) AS age"
        f" FROM ml_items i JOIN {table} v ON v.item_id = i.item_id"
        " WHERE i.status = 'active' AND i.gone_at IS NULL"
        ") x WHERE age > :target"
    )


def _measure_swept(db: Session, name: str, table: str, target: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {"target": target * LATE_TOLERANCE}
    if name in SWEEP_GRACE:
        first_tick = db.execute(_FIRST_SWEEP_TICK, {"scope": f"%,{name},%"}).scalar()
        if first_tick is None:  # never swept yet: nothing can be late
            return {"target_seconds": target, "late": 0, "oldest_late_seconds": None}
        params["first_tick"] = first_tick
    row = db.execute(_swept_sql(table, since_first_tick=name in SWEEP_GRACE), params).one()
    return {"target_seconds": target, "late": row.late, "oldest_late_seconds": _number(row.oldest)}


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
                "target": targets[name] * LATE_TOLERANCE,
            },
        ).one()
        resources[name] = {
            "target_seconds": targets[name],
            "late": row.late,
            "oldest_late_seconds": _number(row.oldest),
        }
    for name, table in SWEPT.items():
        if name not in collected or config["sweep.enabled"].value is not True:
            continue
        resources[name] = _measure_swept(db, name, table, targets[name])
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


def _duration(seconds: float, *, up: bool = False) -> str:
    """Minutes, or hours from two hours on. A delay (`up`) rounds up, so one just past its target never reads as
    the target itself ("2 min, objetivo 2 min", owner 2026-11-03)."""
    minutes = seconds / 60
    value, unit = (minutes / 60, "h") if minutes >= 120 else (minutes, "min")
    return f"{math.ceil(value - 1e-9) if up else round(value)} {unit}"


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
                f"la más atrasada {_duration(measured['oldest_late_seconds'], up=True)} "
                f"(objetivo {_duration(measured['target_seconds'])})"
            )
    return "\n".join(lines)


BACK_MESSAGE = "Pricing: los datos de ML volvieron a estar al día."


def late_resources(report: Mapping[str, Any]) -> List[str]:
    """The names of the late resources of `report`, sorted."""
    return sorted(name for name, measured in report["resources"].items() if measured["late"])
