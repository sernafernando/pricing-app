"""Operator actions on the ML publications store, shared by the admin router and the CLIs (design D19).

- `list_settings` / `update_setting`: the runtime settings, through the `settings_store` allow-list and
  validation (nothing is validated twice). Turning a flag ON also marks its handler `requested`, so it runs on
  the very next worker pass instead of waiting for its schedule.
- `enqueue_items`: manual refresh entries at lane 0. They never bypass pacing: the refresh handler serves them,
  and only while `refresh.enabled` is on (with it off they are accepted and wait; the answer says so).
- `request_job`: `worker_job_state.state = 'requested'` for one handler, optionally with the next scan lap's mode.
  The runtime clears the mark only after a SUCCESSFUL run, so a request made while the handler is off is honored
  once it is enabled. No wake-up is sent: the worker's safety poll picks the mark up on its next pass.

Nothing here calls ML. Functions that write take the caller's session and commit it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_publications import queue, settings_store
from app.services.ml_publications.resources import BUNDLE_RESOURCE, CORE_RESOURCE

SCAN_JOB = "scan"
# A MercadoLibre item id such as MLA935110613 (also what the enqueue CLI accepts).
ITEM_ID_PATTERN = r"^[A-Z]{3}\d+$"

# job name (as in the URL and the status report) -> (worker handler name, the flag that turns it on)
JOBS: Dict[str, Tuple[str, str]] = {
    "refresh": ("ml_publications.refresh", "refresh.enabled"),
    "intake": ("ml_publications.intake", "intake.enabled"),
    "relink": ("ml_publications.relink", "links.enabled"),
    "scan": ("ml_publications.scan", "scan.enabled"),
    "missed_feeds": ("ml_publications.missed_feeds", "missed_feeds.enabled"),
    "sweep": ("ml_publications.sweep", "sweep.enabled"),
}
FLAG_HANDLER: Dict[str, str] = {flag: handler for handler, flag in JOBS.values()}

_REQUEST_SQL = text(
    "INSERT INTO worker_job_state (name, state) VALUES (:name, 'requested') "
    "ON CONFLICT (name) DO UPDATE SET state = 'requested'"
)


class AdminError(Exception):
    """Base of the refusals the router maps to HTTP errors."""


class UnknownSetting(AdminError):
    pass


class InvalidSetting(AdminError):
    pass


class UnknownJob(AdminError):
    pass


class ModeNotApplicable(AdminError):
    pass


def list_settings() -> Dict[str, Any]:
    """Every allow-listed key with its effective value and where it comes from."""
    effective = settings_store.get_settings(sorted(settings_store.SETTING_DEFS))
    return {
        "kill_switch": settings.ML_PUB_KILL_SWITCH is True,
        "settings": [{"key": s.key, "value": s.value, "source": s.source} for s in effective.values()],
    }


def mark_requested(db: Session, handler: str) -> None:
    """Ask the worker to run `handler` on its next pass (joins the caller's transaction)."""
    db.execute(_REQUEST_SQL, {"name": handler})


def update_setting(db: Session, key: str, value: Any, updated_by: str) -> Dict[str, Any]:
    """Write one setting (allow-list and validation of `settings_store`) and answer its effective value."""
    if key not in settings_store.SETTING_DEFS:
        raise UnknownSetting(key)
    handler = FLAG_HANDLER.get(key) if value is True else None
    try:
        settings_store.set_setting(key, value, updated_by, session=db)
        if handler:
            mark_requested(db, handler)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise InvalidSetting(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    effective = settings_store.get_setting(key)  # the kill switch can still force a flag off
    return {"key": key, "value": effective.value, "source": effective.source, "requested": handler}


def enqueue_items(db: Session, item_ids: Sequence[str], resources: Sequence[str]) -> Dict[str, Any]:
    """Enqueue `item_ids` at lane 0 for `resources` and report what will actually happen to them."""
    unique = list(dict.fromkeys(item_ids))
    entries = [
        queue.EnqueueEntry(kind="item", entity_id=i, lane=queue.LANE_MANUAL, resources=tuple(resources)) for i in unique
    ]
    try:
        queue.enqueue(entries, session=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    refresh_enabled = settings_store.is_enabled("refresh")
    in_bundle = settings_store.get_setting("bundle_resources").value
    return {
        "enqueued": len(unique),
        "lane": queue.LANE_MANUAL,
        "resources": list(resources),
        "refresh_enabled": refresh_enabled,
        "note": None if refresh_enabled else "refresh.enabled is off: the entries wait until it is turned on",
        # The refresh handler drops a named resource that `bundle_resources` does not list.
        "missing_from_bundle_resources": sorted(
            {r for r in resources if r not in (BUNDLE_RESOURCE, CORE_RESOURCE) and r not in in_bundle}
        ),
    }


def resolve_job(name: str) -> Tuple[str, str]:
    """`(job, handler)` for a job name or a full handler name."""
    for job, (handler, _flag) in JOBS.items():
        if name in (job, handler):
            return job, handler
    raise UnknownJob(name)


def request_job(db: Session, name: str, *, mode: Optional[str], actor: str) -> Dict[str, Any]:
    """Mark a handler requested; for `scan`, `mode` is written to `scan.next_mode` in the same transaction."""
    job, handler = resolve_job(name)
    if mode is not None and job != SCAN_JOB:
        raise ModeNotApplicable(job)
    try:
        if mode is not None:
            settings_store.set_setting("scan.next_mode", mode, actor, session=db)
        mark_requested(db, handler)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise InvalidSetting(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    flag = JOBS[job][1]
    enabled = settings_store.get_setting(flag).value is True
    return {
        "job": job,
        "handler": handler,
        "requested": True,
        "mode": mode,
        "enabled": enabled,
        "note": None if enabled else f"{flag} is off: the request is kept and runs once it is turned on",
    }
