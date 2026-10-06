"""Job handlers of the ML publications store (design D1, D10, D12, D17, D19).

They run in their own worker process (`pricing-worker-ml.service`, registry
`ML_PUBLICATIONS_REGISTRY`), so ML pacing sleeps never delay the sales drain.

Every handler is gated by a DB-backed flag (`ml_pub_settings`, env default off,
`ML_PUB_KILL_SWITCH` overriding everything). A disabled handler returns the
disabled outcome BEFORE any queue read, ML call or write.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text

from app.core import database
from app.core.config import settings
from app.services.ml_publications import intake as intake_core
from app.services.ml_publications import queue, settings_store, store
from app.services.ml_publications.ml_http import (
    ERROR_INVALID_JSON,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    OUTCOME_NO_TOKEN,
    OUTCOME_NOT_CONFIGURED,
    MlHttpClient,
    MlResponse,
)
from app.services.ml_publications.pacing import DEADLINE, Pacer
from app.services.ml_publications.parsers.items_bulk import BulkElement, MalformedBulkResponse, parse_items_bulk
from app.services.ml_publications.resources import BUNDLE_RESOURCE, CORE_RESOURCE, RESOURCES
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

REFRESH_HANDLER = "ml_publications.refresh"


def disabled_outcome() -> JobResult:
    """The result of a handler whose flag is off (design D17).

    `success=False` on purpose: `WorkerRuntime._record_job_run` then writes only
    `last_run_at`, never `last_success_at`, so `scheduling.is_due` keeps the handler
    due and enabling it later runs it on the very next pass instead of tomorrow. A
    pending on-demand request flag also stays set (the runtime clears it on success only)."""
    return JobResult(success=False, detail={"disabled": True})


# Settings the refresh handler reads at the start of a run and at every batch boundary.
_SETTING_KEYS = (
    "refresh.enabled",
    "events.enabled",
    "bundle_resources",
    "bulk_max_ids",
    "rate_per_sec",
    "stock_rate_per_min",
    "low_lane_min_share",
)
ITEM_KIND = "item"
CORE = CORE_RESOURCE
BUNDLE = BUNDLE_RESOURCE
# After a failure that is not the entry's fault (bad token, missing credentials) the claims go back
# uncharged but not immediately: a tight loop of 5 s passes would hammer the same failure.
UNAUTHORIZED_DELAY = timedelta(seconds=60)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Run:
    """Tallies of one run; `error`/`stopped` end the claim loop."""

    def __init__(self) -> None:
        self.claimed = 0
        self.batches = 0
        self.applied = 0
        self.failed = 0
        self.called = False
        self.error: Optional[str] = None
        self.stopped: Optional[str] = None

    def as_detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {"claimed": self.claimed, "batches": self.batches, "applied": self.applied}
        detail["failed"] = self.failed
        if self.error:
            detail["error"] = self.error
        if self.stopped:
            detail["stopped"] = self.stopped
        return detail


class RefreshHandler:
    """`ml_publications.refresh`: claims queued items and refreshes them from `/items/bulk`.

    Only the item core has a fetcher so far. Any other requested resource is dropped from
    its entry without charging an attempt (design D12): intake and manual enqueues can name
    resources whose code ships in a later PR without poisoning the queue.
    """

    name = REFRESH_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=5)
    run_at_local: Optional[time] = None

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))
        self._client: Optional[MlHttpClient] = None
        self._fairness: Optional[queue.LaneFairness] = None
        self._fairness_share: Optional[float] = None
        # Cumulative since process start, flushed into `worker_job_state.detail.counters`.
        self._elements: Counter = Counter()
        self._skipped_no_fetcher: Counter = Counter()
        self._apply_counters = store.ApplyCounters()
        # `events.enabled` as of the current batch boundary (read with the other settings).
        self._events_enabled = False

    # --- run ---------------------------------------------------------------------------

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SETTING_KEYS)
        if config["refresh.enabled"].value is not True:
            return disabled_outcome()
        self._events_enabled = config["events.enabled"].value is True
        run = _Run()
        try:
            while _utcnow() < ctx.deadline:
                if config["refresh.enabled"].value is not True:
                    run.stopped = "disabled"
                    break
                self._apply_budget(config)
                claims = queue.claim(
                    limit=config["bulk_max_ids"].value,
                    worker_id=ctx.worker_name,
                    kinds=[ITEM_KIND],
                    lanes_desc=self._lane_fairness(config["low_lane_min_share"].value).next_lanes_desc(),
                )
                if not claims:
                    break
                run.claimed += len(claims)
                run.batches += 1
                self._process_batch(ctx, claims, config["bundle_resources"].value, run)
                if run.error or run.stopped:
                    break
                config = settings_store.get_settings(_SETTING_KEYS)
                self._events_enabled = config["events.enabled"].value is True
        finally:
            if run.claimed or run.called:
                self._flush_counters(run)
        return JobResult(success=run.error is None, detail=run.as_detail(), error=run.error)

    def _apply_budget(self, config: Dict[str, settings_store.Setting]) -> None:
        self.pacer.configure(
            rate_per_sec=config["rate_per_sec"].value, stock_rate_per_min=config["stock_rate_per_min"].value
        )

    def _lane_fairness(self, share: float) -> queue.LaneFairness:
        if self._fairness is None or self._fairness_share != share:
            self._fairness = queue.LaneFairness(share)
            self._fairness_share = share
        return self._fairness

    def _http(self) -> MlHttpClient:
        if self._client is None:
            self._client = self._client_factory(self.pacer)
        return self._client

    # --- one batch ---------------------------------------------------------------------

    def _process_batch(
        self, ctx: WorkerContext, claims: Sequence[queue.QueueClaim], bundle_resources: Sequence[str], run: _Run
    ) -> None:
        dropped: Dict[Tuple[str, str], Set[str]] = {}
        core_claims: List[queue.QueueClaim] = []
        for claim in claims:
            needs_core, skipped = _plan(claim, bundle_resources)
            dropped[claim.key] = skipped
            if needs_core:
                core_claims.append(claim)
            else:  # nothing this PR can fetch: settle the entry, no ML call, nothing charged
                self._finish(claim, succeeded=set(claim.resources), failed={}, dropped=skipped)
        if not core_claims:
            return
        if _utcnow() >= ctx.deadline:
            self._release(core_claims, _utcnow())
            run.stopped = "deadline"
            return
        run.called = True
        ids = [c.entity_id for c in core_claims]
        response = self._http().get("items_bulk", f"/items/bulk?ids={','.join(ids)}", deadline=ctx.deadline)
        self._handle_response(ctx, core_claims, dropped, response, run)

    def _handle_response(
        self,
        ctx: WorkerContext,
        claims: List[queue.QueueClaim],
        dropped: Dict[Tuple[str, str], Set[str]],
        response: MlResponse,
        run: _Run,
    ) -> None:
        if response.error == DEADLINE:
            self._release(claims, _utcnow())
            run.stopped = "deadline"
        elif response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN) or response.status == 401:
            self._release(claims, _utcnow() + UNAUTHORIZED_DELAY)
            run.error = "unauthorized" if response.status == 401 else str(response.error)
        elif response.status == 429:
            self._release(claims, _utcnow() + timedelta(seconds=max(1.0, self.pacer.cooldown_remaining())))
            run.stopped = "rate_limited"
        elif response.error in (ERROR_TIMEOUT, ERROR_NETWORK, ERROR_INVALID_JSON) or not 200 <= response.status < 300:
            self._fail_all(claims, dropped, response.error or f"HTTP {response.status}", run)
        else:
            self._apply_elements(ctx, claims, dropped, response, run)

    def _apply_elements(
        self,
        ctx: WorkerContext,
        claims: List[queue.QueueClaim],
        dropped: Dict[Tuple[str, str], Set[str]],
        response: MlResponse,
        run: _Run,
    ) -> None:
        try:
            elements = parse_items_bulk([c.entity_id for c in claims], response.body, filtered=False)
        except MalformedBulkResponse as exc:
            self._fail_all(claims, dropped, f"malformed_bulk_response: {exc}"[:300], run)
            return
        spec = RESOURCES["item"]
        unprocessed: List[queue.QueueClaim] = []
        for claim, element in zip(claims, elements):
            if _utcnow() >= ctx.deadline:
                unprocessed.append(claim)
                continue
            error = self._apply_one(spec, claim, element, response)
            if error is None:
                run.applied += 1
                self._finish(claim, succeeded=set(claim.resources), failed={}, dropped=dropped[claim.key])
            else:
                run.failed += 1
                self._finish(claim, succeeded=dropped[claim.key], failed={CORE: error}, dropped=dropped[claim.key])
        if unprocessed:
            self._release(unprocessed, _utcnow())
            run.stopped = "deadline"

    def _apply_one(self, spec, claim: queue.QueueClaim, element: BulkElement, response: MlResponse) -> Optional[str]:
        """Write one element through the store; returns the failure to charge, or None."""
        if element.status not in (200, 404):
            self._elements["failed"] += 1
            error: Optional[str] = f"HTTP {element.status}"
        else:
            error = None
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
                spec,
                (claim.entity_id,),
                item_response,
                trigger_received_at=claim.source_received_at,
                counters=self._apply_counters,
                events_enabled=self._events_enabled,
            )
        except Exception as exc:  # noqa: BLE001 -- one item's failure must not lose the batch
            logger.exception("apply_fetch failed for %s", claim.entity_id)
            if error is None:
                self._elements["failed"] += 1
            return f"apply failed: {type(exc).__name__}: {exc}"[:300]
        if error is None and outcome.kind == "error_recorded":
            self._elements["failed"] += 1
            return "item body rejected"
        if error is None:
            self._elements[str(element.status)] += 1
        return error

    # --- queue bookkeeping --------------------------------------------------------------

    def _finish(
        self, claim: queue.QueueClaim, *, succeeded: Set[str], failed: Dict[str, str], dropped: Set[str]
    ) -> None:
        outcome = queue.complete(claim, succeeded=succeeded, failed=failed)
        if outcome != queue.OUTCOME_NOT_OWNER:
            for resource in dropped:
                self._skipped_no_fetcher[resource] += 1

    def _fail_all(
        self,
        claims: Sequence[queue.QueueClaim],
        dropped: Dict[Tuple[str, str], Set[str]],
        error: str,
        run: _Run,
    ) -> None:
        for claim in claims:
            run.failed += 1
            self._finish(claim, succeeded=dropped[claim.key], failed={CORE: error}, dropped=dropped[claim.key])

    @staticmethod
    def _release(claims: Sequence[queue.QueueClaim], not_before: datetime) -> None:
        queue.release(claims, pending={}, not_before=not_before)

    # --- counters -------------------------------------------------------------------------

    def _flush_counters(self, run: _Run) -> None:
        elements = {"200": 0, "404": 0, "failed": 0, **self._elements}
        counters = {
            "endpoints": self._client.counters.snapshot() if self._client else {},
            "elements": elements,
            "stale_discarded": self._apply_counters.stale_discarded,
            "noise_suppressed": sum(self._apply_counters.noise_suppressed.values()),
            "skipped_no_fetcher": dict(self._skipped_no_fetcher),
            "skipped_disabled": {},
        }
        detail = {"counters": counters, "last_run": {**run.as_detail(), "at": _utcnow().isoformat()}}
        _persist_detail(self.name, detail)


def _persist_detail(name: str, detail: Dict[str, Any]) -> None:
    """Write `worker_job_state.detail` for `name`. Observability must never fail a run."""
    try:
        with database.get_background_db() as db:
            db.execute(
                text(
                    "INSERT INTO worker_job_state (name, detail) VALUES (:name, CAST(:detail AS jsonb)) "
                    "ON CONFLICT (name) DO UPDATE SET detail = EXCLUDED.detail"
                ),
                {"name": name, "detail": json.dumps(detail)},
            )
    except Exception:  # noqa: BLE001
        logger.exception("could not flush %s counters", name)


def _plan(claim: queue.QueueClaim, bundle_resources: Sequence[str]) -> Tuple[bool, Set[str]]:
    """What an entry needs: (is the item core wanted, resources that have no fetcher and are dropped)."""
    needs_core = False
    dropped: Set[str] = set()
    for resource in claim.resources:
        if resource in (CORE, BUNDLE):
            needs_core = True
        if resource == BUNDLE:
            dropped.update(name for name in bundle_resources if name not in (CORE, BUNDLE))
        elif resource != CORE:
            dropped.add(resource)
    return needs_core, dropped


INTAKE_HANDLER = "ml_publications.intake"
_INTAKE_KEYS = ("intake.enabled", "intake.topics")


class IntakeHandler:
    """`ml_publications.intake`: turns bridge `webhook_latest` notifications into queue entries.

    It only enqueues (lane 1); with `refresh.enabled` off nothing is fetched and nothing is lost,
    the entries wait in the queue. The bridge is only ever read (design D13).
    """

    name = INTAKE_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=15)
    run_at_local: Optional[time] = None

    def __init__(self, *, bridge_engine: Optional[Callable[[], Any]] = None) -> None:
        self._bridge_engine = bridge_engine or (lambda: database.get_mlwebhook_engine())
        self._totals: Counter = Counter()  # cumulative since process start, mirrors the cursor columns
        self._memory = intake_core.OverlapMemory()  # rows the overlap window must not enqueue twice

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_INTAKE_KEYS)
        if config["intake.enabled"].value is not True:
            return disabled_outcome()
        mappings = intake_core.topic_mappings(config["intake.topics"].value)

        def keep_going() -> bool:
            # The flag is re-read at every batch boundary, so turning it off stops the pass promptly.
            return _utcnow() < ctx.deadline and settings_store.get_setting("intake.enabled").value is True

        result = intake_core.run_pass(
            mappings,
            bridge_engine=self._bridge_engine,
            seller_id=settings.ML_USER_ID,
            batch=settings.ML_PUB_INTAKE_BATCH,
            overlap_seconds=settings.ML_PUB_INTAKE_OVERLAP_SECONDS,
            keep_going=keep_going,
            memory=self._memory,
        )
        stats = result.stats.as_dict()
        if stats["rows_read"] or stats["overlap_rows"] or result.error:
            self._flush_counters(stats, result.error)
        return JobResult(success=result.error is None, detail=stats, error=result.error)

    def _flush_counters(self, stats: Dict[str, int], error: Optional[str]) -> None:
        self._totals.update(stats)
        if error:
            self._totals[f"error_{error.split(':')[0]}"] += 1
        detail = {
            "counters": dict(self._totals),
            "last_run": {**stats, "error": error, "at": _utcnow().isoformat()},
        }
        _persist_detail(self.name, detail)


refresh = RefreshHandler()
intake = IntakeHandler()
