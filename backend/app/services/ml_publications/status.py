"""Status report of the ML publications store (spec "Admin status endpoint", "Freshness and completeness
metrics", "Events behind a flag and observable").

One read-only pass over the store's own tables, built for `GET /ml-publications/status`:

- The session is put in `READ ONLY` mode and given `statement_timeout = 5s` first, so "no write" and "bounded
  time" are guarantees of the database, not promises of this module.
- No ML call: nothing here imports the HTTP client.
- Every section runs in its own savepoint. A section that fails (a timeout on a very large table, a missing
  table in a half-migrated schema) is listed in `sections_failed` and reported as null; the rest still answers.
- Queries go over indexed columns or over narrow typed columns (never the `raw` JSON): the biggest are one
  pass over `ml_items` for the status counts, and one `percentile_cont` pass per state table (about 25k narrow
  values each).
- An empty store answers zeros and nulls.

The state of the jobs comes from `worker_job_state` (written by the worker runtime and the handlers), the
effective flags from `settings_store`, and the sweep and missed-feeds health from `ml_pub_job_runs.outcome`: a
sweep tick that fails still returns success to the runtime, so its `last_success_at` says nothing about it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_publications import links, queue, settings_store
from app.services.ml_publications.admin import JOBS

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT = "5s"
PARKED_LIMIT = 20
TOP_PATHS_LIMIT = 20

FLAGS = tuple(key[: -len(".enabled")] for key in settings_store.SETTING_DEFS if key.endswith(".enabled"))
LANES = (queue.LANE_MANUAL, queue.LANE_NOTIFICATION, queue.LANE_RECONCILE, queue.LANE_BACKFILL, queue.LANE_SWEEP)

# resource -> state table; every one carries `last_checked_at` and `http_status`.
STATE_TABLES: Dict[str, str] = {
    "items": "ml_items",
    "description": "ml_item_descriptions",
    "prices": "ml_item_prices",
    "sale_price": "ml_item_sale_prices",
    "promotions": "ml_item_seller_promotions",
    "user_product": "ml_user_products",
    "stock": "ml_user_product_stock",
    "family": "ml_user_product_families",
    "competition": "ml_item_competition",
    "moderation": "ml_item_moderations",
    "performance": "ml_item_performance",
    "visits": "ml_item_visits",
    # Only Full user products have a replenishment row, so it has no EXPECTED_ROW (missing stays 0).
    "replenishment": "ml_user_product_replenishment",
}
# sub-resource -> (key column of its table, column of `ml_items` holding that key): an item that has the
# column set is expected to have a row.
EXPECTED_ROW: Dict[str, Tuple[str, str]] = {
    **{name: ("item_id", "item_id") for name in ("description", "prices", "sale_price", "promotions")},
    **{name: ("item_id", "item_id") for name in ("competition", "moderation", "performance", "visits")},
    "user_product": ("user_product_id", "user_product_id"),
    "stock": ("user_product_id", "user_product_id"),
    "family": ("family_id", "family_id"),
}


def _number(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _guarded(db: Session, name: str, build: Callable[[Session], Any], failed: List[str]) -> Any:
    """Run one section in a savepoint; a failure is reported, never raised."""
    try:
        with db.begin_nested():
            return build(db)
    except Exception:  # noqa: BLE001 -- one section must not take the whole report down
        logger.exception("ml publications status: section %s failed", name)
        failed.append(name)
        return None


# --- jobs and flags ---------------------------------------------------------------------------------


def _worker_states(db: Session) -> Dict[str, Dict[str, Any]]:
    rows = db.execute(
        text("SELECT name, last_run_at, last_success_at, state, detail FROM worker_job_state WHERE name = ANY(:names)"),
        {"names": [handler for handler, _ in JOBS.values()]},
    ).mappings()
    return {row["name"]: dict(row) for row in rows}


def _jobs(flags: Dict[str, bool], states: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    jobs = []
    for job, (handler, flag_key) in JOBS.items():
        state = states.get(handler) or {}
        detail = state.get("detail") or {}
        enabled = flags[flag_key[: -len(".enabled")]]
        disabled = not enabled or detail.get("disabled") is True
        last_run, last_success = state.get("last_run_at"), state.get("last_success_at")
        error = detail.get("error") or (detail.get("last_run") or {}).get("error")
        jobs.append(
            {
                "job": job,
                "handler": handler,
                "flag": flag_key,
                "enabled": enabled,
                "disabled": disabled,  # a flag that is off is a state, not a failure
                "requested": state.get("state") == "requested",
                "last_run_at": last_run,
                "last_success_at": last_success,
                "failing": not disabled and last_run is not None and (last_success is None or last_run > last_success),
                "last_error": None if error is None else str(error),  # a handler may store anything
            }
        )
    return jobs


# --- queue, intake, backfill ------------------------------------------------------------------------

_WAITING = "claimed_at IS NULL AND parked_at IS NULL"
_LANES_SQL = text(
    f"""
    SELECT lane,
           count(*) FILTER (WHERE {_WAITING}) AS waiting,
           count(*) FILTER (WHERE claimed_at IS NOT NULL) AS claimed,
           count(*) FILTER (WHERE parked_at IS NOT NULL) AS parked,
           CAST(extract(epoch FROM now() - min(first_enqueued_at) FILTER (WHERE {_WAITING})) AS double precision)
               AS oldest
    FROM ml_pub_refresh_queue GROUP BY lane
    """
)
_PARKED_SQL = text(
    "SELECT kind, entity_id, lane, attempts, left(last_error, 500) AS last_error, parked_at "
    "FROM ml_pub_refresh_queue WHERE parked_at IS NOT NULL ORDER BY parked_at DESC LIMIT :limit"
)


def _queue(db: Session) -> Dict[str, Any]:
    found = {row["lane"]: row for row in db.execute(_LANES_SQL).mappings()}
    lanes = []
    for lane in sorted({*LANES, *found}):
        row = found.get(lane)
        lanes.append(
            {
                "lane": lane,
                "waiting": row["waiting"] if row else 0,
                "claimed": row["claimed"] if row else 0,
                "parked": row["parked"] if row else 0,
                "oldest_waiting_age_seconds": row["oldest"] if row else None,
            }
        )
    parked = [dict(row) for row in db.execute(_PARKED_SQL, {"limit": PARKED_LIMIT}).mappings()]
    return {"lanes": lanes, "parked": parked, "parked_total": sum(lane["parked"] for lane in lanes)}


_CURSORS_SQL = text(
    "SELECT topic, cursor_received_at, updated_at, rows_read, enqueued, skipped_satisfied, skipped_foreign_seller, "
    "unparsed, CAST(extract(epoch FROM now() - COALESCE(updated_at, cursor_received_at)) AS double precision) "
    "AS age_seconds FROM ml_pub_intake_cursors ORDER BY topic"
)


def _intake(db: Session, enabled: bool) -> Dict[str, Any]:
    """A cursor is stalled when it has not advanced (`updated_at` only moves with it) for longer than
    `ML_PUB_INTAKE_STALL_SECONDS` while the flag is on; with the flag off an old cursor is not an alarm."""
    stall = settings.ML_PUB_INTAKE_STALL_SECONDS
    cursors = []
    for row in db.execute(_CURSORS_SQL).mappings():
        cursor = dict(row)
        cursor["stalled"] = enabled and cursor["age_seconds"] is not None and cursor["age_seconds"] > stall
        cursors.append(cursor)
    return {
        "enabled": enabled,
        "stall_seconds": stall,
        "stalled": any(cursor["stalled"] for cursor in cursors),
        "cursors": cursors,
    }


_BACKFILL_SQL = text(
    "SELECT status, mode, pages, enumerated, enqueued, restarts, unsupported, lap_started_at, started_at, "
    "completed_at, last_error, (completed_at IS NOT NULL AND (lap_started_at IS NULL OR completed_at >= lap_started_at)) "
    "AS complete FROM ml_pub_scan_state ORDER BY status"
)


def _backfill(db: Session) -> List[Dict[str, Any]]:
    return [dict(row) for row in db.execute(_BACKFILL_SQL).mappings()]


# --- job runs: missed feeds and sweep ----------------------------------------------------------------

_LAST_RUN_SQL = text(
    "SELECT started_at, finished_at, outcome, last_error, counts FROM ml_pub_job_runs "
    "WHERE job = :job ORDER BY started_at DESC LIMIT 1"
)
_LAST_SUCCESS_SQL = text(
    "SELECT finished_at, CAST(extract(epoch FROM now() - finished_at) AS double precision) AS age_seconds "
    "FROM ml_pub_job_runs WHERE job = 'missed_feeds' AND outcome = 'success' AND finished_at IS NOT NULL "
    "ORDER BY started_at DESC LIMIT 1"
)
_LAST_GAP_SQL = text(
    "SELECT started_at, counts -> 'coverage_gap' AS gap FROM ml_pub_job_runs "
    "WHERE job = 'missed_feeds' AND counts -> 'coverage_gap' IS NOT NULL ORDER BY started_at DESC LIMIT 1"
)


def _run_summary(db: Session, job: str) -> Optional[Dict[str, Any]]:
    row = db.execute(_LAST_RUN_SQL, {"job": job}).mappings().first()
    if row is None:
        return None
    counts = row["counts"] or {}
    return {
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "outcome": row["outcome"],
        "error": row["last_error"],
        "enqueued": counts.get("enqueued") or 0,
        "yielded_in_a_row": counts.get("yielded_in_a_row") or 0,
    }


def _missed_feeds(db: Session) -> Dict[str, Any]:
    success = db.execute(_LAST_SUCCESS_SQL).mappings().first()
    gap_row = db.execute(_LAST_GAP_SQL).mappings().first()
    gap = None
    if gap_row is not None:
        resolved = success is not None and success["finished_at"] > gap_row["started_at"]
        gap = {**(gap_row["gap"] or {}), "recorded_at": gap_row["started_at"], "resolved": resolved}
    last_run = _run_summary(db, "missed_feeds")
    if last_run is not None:
        last_run = {key: last_run[key] for key in ("started_at", "finished_at", "outcome", "error")}
    return {
        "last_success_at": success["finished_at"] if success else None,
        "age_seconds": success["age_seconds"] if success else None,
        "last_run": last_run,
        "coverage_gap": gap,
    }


def _sweep(db: Session) -> Dict[str, Any]:
    return {"last_run": _run_summary(db, "sweep")}


DIVERGENCE_LISTED = 20  # pairs of the latest divergence run shown in the report


def _verification(db: Session) -> Dict[str, Any]:
    """The latest divergence spot-check (rate, flag, diverging pairs) and freshness snapshot (outcome, size)."""
    divergence = db.execute(_LAST_RUN_SQL, {"job": "divergence"}).mappings().first()
    snapshot = db.execute(_LAST_RUN_SQL, {"job": "freshness"}).mappings().first()
    if divergence is not None:
        counts = divergence["counts"] or {}
        divergence = {
            "started_at": divergence["started_at"],
            "finished_at": divergence["finished_at"],
            "outcome": divergence["outcome"],
            "error": divergence["last_error"],
            "rate": counts.get("rate"),
            "target": counts.get("target"),
            "below_target": counts.get("below_target") is True,
            "sampled": counts.get("sampled") or 0,
            "divergence_pairs": counts.get("divergence_pairs") or 0,
            "changed_after_sampling_items": counts.get("changed_after_sampling_items") or 0,
            "divergences": (counts.get("divergences") or [])[:DIVERGENCE_LISTED],
        }
    if snapshot is not None:
        snapshot = {
            "started_at": snapshot["started_at"],
            "finished_at": snapshot["finished_at"],
            "outcome": snapshot["outcome"],
            "error": snapshot["last_error"],
            "items": ((snapshot["counts"] or {}).get("items") or {}).get("total"),
        }
    return {"divergence": divergence, "snapshot": snapshot}


# --- items, freshness, lag, completeness --------------------------------------------------------------


def _items(db: Session) -> Dict[str, Any]:
    rows = db.execute(
        text(
            "SELECT status, count(*) AS n, count(raw) AS with_raw, count(gone_at) AS gone FROM ml_items GROUP BY status"
        )
    ).all()
    return {
        "total": sum(row.n for row in rows),
        "with_raw": sum(row.with_raw for row in rows),
        "gone": sum(row.gone for row in rows),
        "by_status": {(row.status or "unknown"): row.n for row in rows},
    }


def _freshness(db: Session) -> Dict[str, Dict[str, Any]]:
    result = {}
    for resource, table in STATE_TABLES.items():
        row = db.execute(
            text(
                "SELECT count(*) AS total, count(age) AS checked, "
                "percentile_cont(0.5) WITHIN GROUP (ORDER BY age) AS p50, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY age) AS p95, max(age) AS oldest FROM "
                f"(SELECT CAST(extract(epoch FROM now() - last_checked_at) AS double precision) AS age FROM {table}) s"
            )
        ).one()
        result[resource] = {
            "rows": row.total,
            "checked": row.checked,
            "p50_age_seconds": _number(row.p50),
            "p95_age_seconds": _number(row.p95),
            "max_age_seconds": _number(row.oldest),
        }
    return result


_LAG_SQL = text(
    "SELECT count(*) AS samples, percentile_cont(0.95) WITHIN GROUP "
    "(ORDER BY CAST(extract(epoch FROM fetched_at - last_trigger_received_at) AS double precision)) AS p95 "
    "FROM ml_items WHERE last_trigger_received_at IS NOT NULL AND fetched_at >= now() - interval '24 hours' "
    "AND fetched_at >= last_trigger_received_at"
)


def _lag(db: Session) -> Dict[str, Any]:
    row = db.execute(_LAG_SQL).one()
    return {"lag_p95_seconds_24h": _number(row.p95), "lag_samples_24h": row.samples}


def _completeness(db: Session, bundle_resources: List[str]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for resource, table in STATE_TABLES.items():
        non_2xx = db.execute(
            text(
                f"SELECT http_status, count(*) FROM {table} "
                "WHERE http_status IS NOT NULL AND http_status NOT BETWEEN 200 AND 299 GROUP BY http_status"
            )
        ).all()
        missing = 0
        if resource in EXPECTED_ROW:
            key, item_column = EXPECTED_ROW[resource]
            missing = db.execute(
                text(
                    f"SELECT count(*) FROM ml_items i WHERE i.gone_at IS NULL AND i.http_status = 200 "
                    f"AND i.{item_column} IS NOT NULL "
                    f"AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{key} = i.{item_column})"
                )
            ).scalar()
        result[resource] = {
            "expected": resource == "items" or resource in bundle_resources,
            "missing": missing,
            "non_2xx": {str(code): count for code, count in non_2xx},
        }
    return result


# --- counters, events, links, paths -----------------------------------------------------------------------


def _counters(states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Cumulative since the ML worker started, flushed by the refresh handler into its state row."""
    counters = ((states.get("ml_publications.refresh") or {}).get("detail") or {}).get("counters") or {}
    requests = counters.get("endpoints") or {}
    return {
        "stale_discarded": counters.get("stale_discarded") or 0,
        "noise_suppressed": counters.get("noise_suppressed") or 0,
        "requests": requests,
        "requests_429": sum((outcomes or {}).get("429", 0) for outcomes in requests.values()),
        "elements": counters.get("elements") or {},
    }


_EVENTS_SQL = text(
    "SELECT event_type, count(*) FILTER (WHERE observed_at >= now() - interval '24 hours') AS last_24h, "
    "count(*) AS last_7d, max(observed_at) AS newest_at FROM ml_item_events "
    "WHERE observed_at >= now() - interval '7 days' GROUP BY event_type"
)
# The newest event overall, whatever its type. Events are small and kept indefinitely: a top-1 sort.
_NEWEST_EVENT_SQL = text(
    "SELECT CAST(extract(epoch FROM now() - observed_at) AS double precision) FROM ml_item_events "
    "ORDER BY observed_at DESC LIMIT 1"
)


def _events(db: Session, enabled: bool) -> Dict[str, Any]:
    by_type = {
        row.event_type: {"last_24h": row.last_24h, "last_7d": row.last_7d, "newest_at": row.newest_at}
        for row in db.execute(_EVENTS_SQL)
    }
    return {
        "enabled": enabled,
        "by_type": by_type,
        "newest_age_seconds": db.execute(_NEWEST_EVENT_SQL).scalar(),
    }


def _links(db: Session, enabled: bool) -> Dict[str, Any]:
    return {"enabled": enabled, "coverage": links.coverage(db, sample_size=0)}


_TOP_PATHS_SQL = text(
    "SELECT resource_type, p AS path, count(*) AS changes FROM ml_change_log, unnest(changed_paths) AS p "
    "WHERE observed_at >= now() - interval '7 days' GROUP BY resource_type, p "
    "ORDER BY changes DESC, resource_type, p LIMIT :limit"
)


def _top_changed_paths(db: Session) -> List[Dict[str, Any]]:
    return [dict(row) for row in db.execute(_TOP_PATHS_SQL, {"limit": TOP_PATHS_LIMIT}).mappings()]


def freshness_metrics(db: Session, bundle_resources: List[str]) -> Dict[str, Any]:
    """The freshness and completeness numbers of the report, for the daily snapshot job (one metric, one source:
    the snapshot stores what the status endpoint computes). Raises on a failure; the caller records it."""
    lag = _lag(db)
    return {
        "items": _items(db),
        "freshness": _freshness(db),
        **lag,
        "completeness": _completeness(db, bundle_resources),
    }


# --- the report ----------------------------------------------------------------------------------------------


def build_status(db: Session) -> Dict[str, Any]:
    """The whole report. Read only; see the module docstring."""
    db.execute(text("SET TRANSACTION READ ONLY"))
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    failed: List[str] = []
    config = settings_store.get_settings([f"{flag}.enabled" for flag in FLAGS] + ["bundle_resources"])
    flags = {flag: config[f"{flag}.enabled"].value is True for flag in FLAGS}
    bundle_resources = config["bundle_resources"].value
    states = _guarded(db, "worker_state", _worker_states, failed) or {}
    lag = _guarded(db, "lag", _lag, failed) or {"lag_p95_seconds_24h": None, "lag_samples_24h": 0}
    report = {
        "generated_at": datetime.now(timezone.utc),
        "kill_switch": bool(settings.ML_PUB_KILL_SWITCH),
        "flags": flags,
        "jobs": _guarded(db, "jobs", lambda _s: _jobs(flags, states), failed) or [],
        "queue": _guarded(db, "queue", _queue, failed),
        "intake": _guarded(db, "intake", lambda s: _intake(s, flags["intake"]), failed),
        "backfill": _guarded(db, "backfill", _backfill, failed),
        "missed_feeds": _guarded(db, "missed_feeds", _missed_feeds, failed),
        "sweep": _guarded(db, "sweep", _sweep, failed),
        "verification": _guarded(db, "verification", _verification, failed),
        "items": _guarded(db, "items", _items, failed),
        "freshness": _guarded(db, "freshness", _freshness, failed),
        **lag,
        "completeness": _guarded(db, "completeness", lambda s: _completeness(s, bundle_resources), failed),
        "counters": _guarded(db, "counters", lambda _s: _counters(states), failed) or {},
        "events": _guarded(db, "events", lambda s: _events(s, flags["events"]), failed),
        "top_changed_paths": _guarded(db, "top_changed_paths", _top_changed_paths, failed),
    }
    # Last: the coverage service sets its own statement timeout for the rest of the transaction.
    report["links"] = _guarded(db, "links", lambda s: _links(s, flags["links"]), failed)
    report["sections_failed"] = failed
    return report
