"""`ml_publications.core_first` (S1c): read the item cores of a notification burst ahead of the sub-resources.

A burst of `items` notifications (~700 in 3 min, prod 2026-11-12) waits in the notification lane (1) while the
refresh walks ~4 calls per entry, so the publication status (target 2 min) goes late although its core is cheap:
`/items/bulk` reads 20 items per call. Every few seconds this handler takes the oldest waiting lane-1 item entries
whose stored core is older than their last notification and reads their cores in groups of `bulk_max_ids`, through
the same request, parser (`parse_items_bulk`) and store (`store.apply_fetch`) the refresh uses. It never claims,
changes or deletes a queue entry: the refresh still processes it for its sub-resources, and skips its core then
(`fresh_cores`), so no item is read twice.

The rule both sides share: a stored core covers an entry when the store's latest observation of the item was
requested at least `CLOCK_SKEW_MARGIN_SECONDS` after the entry's last enqueue
(`ml_items.fetched_request_started_at - margin >= q.last_enqueued_at`). The worker clock stamps the request and
Postgres `now()` stamps the enqueue: the margin keeps a worker clock ahead (up to the margin) from passing off a read
made before a notification as covering it. To make its own reads count, this handler waits until an entry has been
queued for the margin before reading it.
`source_received_at` is not used: it keeps the OLDEST notification of the entry, so a newer one would be missed.
`last_enqueued_at` is bumped by every enqueue and is never earlier than the notification it carries.

Bounds: at most `MAX_GROUPS_PER_TICK` bulk calls per run (3 calls per 5 s, about 6 % of a 10 req/s budget, enough
for 720 items a minute), every call through the shared pacer. A 429 (or its cooldown still running) ends the run;
an item whose core could not be applied is not retried by this handler for the same notification (the refresh
retries it). No session is held across an ML call.

Gated by `core_first.enabled` (env default ON, a kill switch) AND `refresh.enabled`: without the refresh nothing
would settle the entries, and a fresh deploy stays inert.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

from app.core import database
from app.services.ml_publications import queue, settings_store, store
from app.services.ml_publications.ml_http import OUTCOME_NO_TOKEN, OUTCOME_NOT_CONFIGURED, MlHttpClient, MlResponse
from app.services.ml_publications.pacing import DEADLINE, Pacer
from app.services.ml_publications.parsers.items_bulk import MalformedBulkResponse, parse_items_bulk
from app.services.ml_publications.resources import BUNDLE_RESOURCE, CORE_RESOURCE, ITEM_KIND, RESOURCES
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

HANDLER_NAME = "ml_publications.core_first"
BULK_FAMILY = "items_bulk"  # the refresh's pacer family for `/items/bulk`: one cooldown for both
MAX_GROUPS_PER_TICK = 3
# How long an item whose core could not be applied is left to the refresh before this handler tries it again.
TRIED_TTL_SECONDS = 600.0
# Worker clock vs Postgres clock: how far ahead the worker clock may be without a read before a notification being
# taken as covering it. Costs this handler a wait of that long after an enqueue (the status target is 2 minutes).
CLOCK_SKEW_MARGIN_SECONDS = 5.0
_SETTING_KEYS = (
    "core_first.enabled",
    "refresh.enabled",
    "events.enabled",
    "links.enabled",
    "bulk_max_ids",
    "rate_per_sec",
    "stock_rate_per_min",
    "replenishment_rate_per_min",
)

_STALE_SQL = text(
    """
    SELECT q.entity_id, q.last_enqueued_at, q.source_received_at
    FROM ml_pub_refresh_queue q
    LEFT JOIN ml_items i ON i.item_id = q.entity_id
    WHERE q.kind = :kind AND q.lane = :lane
      AND q.claimed_at IS NULL AND q.parked_at IS NULL AND q.not_before <= now()
      AND q.last_enqueued_at <= now() - make_interval(secs => :margin)
      AND q.resources && CAST(:core_resources AS text[])
      AND (
          i.fetched_request_started_at IS NULL
          OR i.fetched_request_started_at - make_interval(secs => :margin) < q.last_enqueued_at
      )
      AND NOT EXISTS (
          SELECT 1 FROM unnest(CAST(:tried_ids AS text[]), CAST(:tried_at AS timestamptz[])) AS t(id, at)
          WHERE t.id = q.entity_id AND t.at = q.last_enqueued_at
      )
    ORDER BY q.first_enqueued_at
    LIMIT :limit
    """
)

_FRESH_SQL = text(
    """
    SELECT q.entity_id, i.gone_at IS NOT NULL AS gone
    FROM ml_pub_refresh_queue q
    JOIN ml_items i ON i.item_id = q.entity_id
    WHERE q.kind = :kind AND q.lane = :lane AND q.entity_id = ANY(CAST(:ids AS text[]))
      AND i.fetched_request_started_at - make_interval(secs => :margin) >= q.last_enqueued_at
    """
)


def fresh_cores(item_ids: Sequence[str]) -> Dict[str, bool]:
    """Of the notification-lane item entries `item_ids`, those whose stored core already covers their last
    notification, mapped to whether the item is gone (its core answered 404). Only lane 1: a manual (0), reconcile,
    backfill or sweep entry asks for a read of its own and always gets it. One short session."""
    if not item_ids:
        return {}
    params = {
        "kind": ITEM_KIND,
        "lane": queue.LANE_NOTIFICATION,
        "ids": list(item_ids),
        "margin": CLOCK_SKEW_MARGIN_SECONDS,
    }
    with database.get_background_db() as session:
        return {row.entity_id: bool(row.gone) for row in session.execute(_FRESH_SQL, params)}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CoreFirstHandler:
    """`ml_publications.core_first`: see the module docstring."""

    name = HANDLER_NAME
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=5)
    run_at_local: Optional[dtime] = None
    own_thread = True

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
        monotonic: Optional[Callable[[], float]] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))
        self._client: Optional[MlHttpClient] = None
        self._monotonic = monotonic or time.monotonic
        self._apply_counters = store.ApplyCounters()
        # item id -> (the `last_enqueued_at` it was tried for, when): not read again for that same notification.
        self._tried: Dict[str, Tuple[datetime, float]] = {}

    def _http(self) -> MlHttpClient:
        if self._client is None:
            self._client = self._client_factory(self.pacer)
        return self._client

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SETTING_KEYS)
        if config["core_first.enabled"].value is not True or config["refresh.enabled"].value is not True:
            return JobResult(success=False, detail={"disabled": True})
        self.pacer.configure(
            rate_per_sec=config["rate_per_sec"].value,
            stock_rate_per_min=config["stock_rate_per_min"].value,
            replenishment_rate_per_min=config["replenishment_rate_per_min"].value,
        )
        detail: Dict[str, Any] = {"calls": 0, "fetched": 0, "failed": 0}
        error: Optional[str] = None
        for _ in range(MAX_GROUPS_PER_TICK):
            stopped = self._stop_reason(ctx)
            if stopped:
                detail["stopped"] = stopped
                break
            entries = self._stale_entries(config["bulk_max_ids"].value)
            if not entries:
                break
            ids = [row.entity_id for row in entries]
            response = self._http().get(BULK_FAMILY, f"/items/bulk?ids={','.join(ids)}", deadline=ctx.deadline)
            if response.error == DEADLINE:
                detail["stopped"] = "stopping" if ctx.stop_requested() else "deadline"
                break
            detail["calls"] += 1
            if response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN) or response.status == 401:
                error = "unauthorized" if response.status == 401 else str(response.error)
                break
            if response.status == 429:
                detail["stopped"] = "rate_limited"
                break
            self._remember(entries)
            if response.error or not 200 <= response.status < 300:
                detail["failed"] += len(entries)
                detail["stopped"] = response.error or f"HTTP {response.status}"
                break
            fetched, failed = self._apply(entries, response, config)
            detail["fetched"] += fetched
            detail["failed"] += failed
        return JobResult(success=error is None, detail=detail, error=error)

    def _stop_reason(self, ctx: WorkerContext) -> Optional[str]:
        if ctx.stop_requested():
            return "stopping"
        if _utcnow() >= ctx.deadline:
            return "deadline"
        if self.pacer.cooldown_remaining(BULK_FAMILY) > 0:  # a 429 of the bulk endpoint: leave it alone until over
            return "rate_limited"
        return None

    def _stale_entries(self, limit: int) -> List[Any]:
        self._forget_expired()
        tried = list(self._tried.items())
        params = {
            "kind": ITEM_KIND,
            "lane": queue.LANE_NOTIFICATION,
            "core_resources": [BUNDLE_RESOURCE, CORE_RESOURCE],
            "tried_ids": [item_id for item_id, _ in tried],
            "tried_at": [at for _, (at, _) in tried],
            "limit": limit,
            "margin": CLOCK_SKEW_MARGIN_SECONDS,
        }
        with database.get_background_db() as session:
            return list(session.execute(_STALE_SQL, params))

    def _remember(self, entries: Sequence[Any]) -> None:
        now = self._monotonic()
        for row in entries:
            self._tried[row.entity_id] = (row.last_enqueued_at, now)

    def _forget_expired(self) -> None:
        horizon = self._monotonic() - TRIED_TTL_SECONDS
        for item_id in [i for i, (_, at) in self._tried.items() if at <= horizon]:
            del self._tried[item_id]

    def _apply(
        self, entries: Sequence[Any], response: MlResponse, config: Dict[str, settings_store.Setting]
    ) -> Tuple[int, int]:
        """Store each element as the refresh does (`store.apply_fetch`, one short transaction each). An entry
        whose core is now stored drops out of the stale query by itself."""
        try:
            elements = parse_items_bulk([row.entity_id for row in entries], response.body, filtered=False)
        except MalformedBulkResponse:
            logger.warning("core_first: malformed /items/bulk response for %d items", len(entries), exc_info=True)
            return 0, len(entries)
        fetched = failed = 0
        for row, element in zip(entries, elements):
            item_response = MlResponse(
                endpoint=response.endpoint,
                status=element.status,
                body=element.body,
                headers=response.headers,
                request_started_at=response.request_started_at,
                received_at=response.received_at,
            )
            try:
                outcome = store.apply_fetch(
                    RESOURCES["item"],
                    (row.entity_id,),
                    item_response,
                    trigger_received_at=row.source_received_at,
                    counters=self._apply_counters,
                    events_enabled=config["events.enabled"].value is True,
                    links_enabled=config["links.enabled"].value is True,
                )
            except Exception:  # noqa: BLE001 -- one item's failure must not lose the group; the refresh retries it
                logger.exception("core_first: apply_fetch failed for %s", row.entity_id)
                failed += 1
                continue
            if element.status in (200, 404) and outcome.kind != "error_recorded":
                fetched += 1
            else:
                failed += 1
        return fetched, failed
