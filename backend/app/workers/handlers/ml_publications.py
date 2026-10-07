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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text

from app.core import database
from app.core.config import settings
from app.services.ml_publications import intake as intake_core
from app.services.ml_publications import (
    bundle,
    links,
    missed_feeds as missed_feeds_core,
    queue,
    scans,
    settings_store,
    store,
    subresource_store,
    sweeps as sweeps_core,
)
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
from app.services.ml_publications.resources import (
    BUNDLE_RESOURCE,
    CORE_RESOURCE,
    FAMILY_KIND,
    ITEM_KIND,
    RESOURCES,
    USER_PRODUCT_KIND,
)
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
    "links.enabled",
    *bundle.FLAG_GATES.values(),
    "bundle_resources",
    "min_age_seconds",
    "bulk_max_ids",
    "rate_per_sec",
    "stock_rate_per_min",
    "low_lane_min_share",
)
# Every kind of entry the refresh handler claims: an item (core, sub-resources, and through its row the user
# product and family), a user product (stock/user product notifications) or a family.
CLAIMED_KINDS = (ITEM_KIND, USER_PRODUCT_KIND, FAMILY_KIND)
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


@dataclass
class _Work:
    """One claimed entry while its batch is processed: what it needs and how far it got."""

    claim: queue.QueueClaim
    plan: bundle.Plan
    core_status: Optional[int] = None  # HTTP status of the item core once it was applied
    core_error: Optional[str] = None  # the core failed: the entry is charged and retried whole
    done: Set[str] = field(default_factory=set)  # sub-resources fetched or skipped by minimum age
    failed: Dict[str, str] = field(default_factory=dict)  # sub-resource -> failure to charge
    settled: bool = False  # completed or released: nothing more to do with the claim

    @property
    def pending(self) -> Set[str]:
        """Sub-resources still to fetch (only meaningful once the core is applied): neither settled (`done`)
        nor already failed (`failed`, charged when the entry settles)."""
        return {name for name in self.plan.wanted if name not in self.done and name not in self.failed}


@dataclass(frozen=True)
class _Interruption:
    """A response that ends the run: why, and when the released claims may be retried."""

    kind: str  # "stopped" or "error"
    reason: str
    not_before: datetime


class RefreshHandler:
    """`ml_publications.refresh`: claims queued items and refreshes them from `/items/bulk`, then
    fetches the sub-resources each entry asks for (`bundle.FETCHERS`: description, prices, sale_price,
    promotions, the user product, stock and family of the item, competition, moderation, performance and
    visits).

    Entries of kind `user_product` and `family` (stock / family notifications, manual) carry no item: they
    fetch only their own resources. An item entry reaches the user product and family through the stored
    item row; an item that has none skips them (`skipped_not_applicable`, not a failure), and two items of
    one user product in a batch fetch it once (`skipped_shared`).

    A sub-resource runs only when it is enabled in `bundle_resources` (default: the core only); promotions
    also need `promotions.enabled`. Performance and visits are sweep-only: a bundle never asks for them.
    Competition and moderation are also skipped, uncharged, for an item they do not apply to
    (`bundle.is_applicable`, counter `skipped_not_applicable`). Any
    other requested resource is dropped from its entry without charging an attempt (design D12):
    intake and manual enqueues can name resources that are disabled or whose code ships in a later
    PR without poisoning the queue. A failing sub-resource is charged to that resource alone: the
    entry keeps only it, so the retry fetches nothing else.
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
        self._skipped_disabled: Counter = Counter()
        self._skipped_min_age: Counter = Counter()
        self._skipped_not_applicable: Counter = Counter()
        self._skipped_shared: Counter = Counter()
        self._requeued_for_core: Counter = Counter()
        self._skipped_item_gone = 0
        self._sub_outcomes: Dict[str, Counter] = defaultdict(Counter)
        self._apply_counters = store.ApplyCounters()
        # `events.enabled` / `links.enabled` as of the current batch boundary (read with the other settings).
        self._events_enabled = False
        self._links_enabled = False

    # --- run ---------------------------------------------------------------------------

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SETTING_KEYS)
        if config["refresh.enabled"].value is not True:
            return disabled_outcome()
        self._events_enabled = config["events.enabled"].value is True
        self._links_enabled = config["links.enabled"].value is True
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
                    kinds=list(CLAIMED_KINDS),
                    lanes_desc=self._lane_fairness(config["low_lane_min_share"].value).next_lanes_desc(),
                )
                if not claims:
                    break
                run.claimed += len(claims)
                run.batches += 1
                self._process_batch(ctx, claims, config, run)
                if run.error or run.stopped:
                    break
                config = settings_store.get_settings(_SETTING_KEYS)
                self._events_enabled = config["events.enabled"].value is True
                self._links_enabled = config["links.enabled"].value is True
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
        self,
        ctx: WorkerContext,
        claims: Sequence[queue.QueueClaim],
        config: Dict[str, settings_store.Setting],
        run: _Run,
    ) -> None:
        bundle_resources = config["bundle_resources"].value
        gated_off = frozenset(name for name, flag in bundle.FLAG_GATES.items() if config[flag].value is not True)
        works: List[_Work] = []
        for claim in claims:
            work = _Work(claim, bundle.plan(claim.resources, bundle_resources, gated_off, claim.kind))
            if work.plan.needs_core or work.plan.wanted:
                works.append(work)
            else:  # nothing this deployment can fetch: settle the entry, no ML call, nothing charged
                self._finish(work)
        core_works = [w for w in works if w.plan.needs_core]
        if core_works:
            if _utcnow() >= ctx.deadline:
                self._release(works, _utcnow())
                run.stopped = "deadline"
                return
            run.called = True
            ids = [w.claim.entity_id for w in core_works]
            response = self._http().get("items_bulk", f"/items/bulk?ids={','.join(ids)}", deadline=ctx.deadline)
            interruption = self._interruption(response)
            if interruption:
                self._end_run(run, interruption)
                self._release(works, interruption.not_before)
                return
            self._handle_core_response(ctx, core_works, response, run)
        self._fetch_subresources(ctx, [w for w in works if not w.settled], config, run)

    def _interruption(self, response: MlResponse) -> Optional[_Interruption]:
        if response.error == DEADLINE:
            return _Interruption("stopped", "deadline", _utcnow())
        if response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN) or response.status == 401:
            reason = "unauthorized" if response.status == 401 else str(response.error)
            return _Interruption("error", reason, _utcnow() + UNAUTHORIZED_DELAY)
        if response.status == 429:
            wait = timedelta(seconds=max(1.0, self.pacer.cooldown_remaining()))
            return _Interruption("stopped", "rate_limited", _utcnow() + wait)
        return None

    @staticmethod
    def _end_run(run: _Run, interruption: _Interruption) -> None:
        if interruption.kind == "error":
            run.error = interruption.reason
        else:
            run.stopped = interruption.reason

    def _handle_core_response(self, ctx: WorkerContext, works: List[_Work], response: MlResponse, run: _Run) -> None:
        if response.error in (ERROR_TIMEOUT, ERROR_NETWORK, ERROR_INVALID_JSON) or not 200 <= response.status < 300:
            self._fail_core(works, response.error or f"HTTP {response.status}", run)
        else:
            self._apply_elements(ctx, works, response, run)

    def _apply_elements(self, ctx: WorkerContext, works: List[_Work], response: MlResponse, run: _Run) -> None:
        try:
            elements = parse_items_bulk([w.claim.entity_id for w in works], response.body, filtered=False)
        except MalformedBulkResponse as exc:
            self._fail_core(works, f"malformed_bulk_response: {exc}"[:300], run)
            return
        spec = RESOURCES["item"]
        unprocessed: List[_Work] = []
        for work, element in zip(works, elements):
            if _utcnow() >= ctx.deadline:
                unprocessed.append(work)
                continue
            error = self._apply_one(spec, work.claim, element, response)
            if error is None:
                run.applied += 1
                work.core_status = element.status
                if not work.plan.wanted:  # nothing else to fetch for this entry
                    self._finish(work)
            else:
                run.failed += 1
                work.core_error = error
                self._finish(work)
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
                links_enabled=self._links_enabled,
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

    # --- sub-resources -----------------------------------------------------------------------

    def _fetch_subresources(
        self,
        ctx: WorkerContext,
        works: List[_Work],
        config: Dict[str, settings_store.Setting],
        run: _Run,
    ) -> None:
        """Walk each remaining entry's sub-resources; an entry settles once all of them were tried."""
        walking: List[_Work] = []
        for work in works:
            if work.core_status == 404:  # the item is gone: its sub-resources would only answer 404
                self._skipped_item_gone += 1
                self._finish(work)
            else:
                walking.append(work)
        targets = self._targets(walking)
        due = self._due_resources(walking, targets, config["min_age_seconds"].value, _utcnow())
        for work in walking:  # settled up front, so an interruption never keeps a resource that is too recent
            for resource in sorted(work.pending):
                if resource not in due[work.claim.key]:
                    self._skipped_min_age[resource] += 1
                    work.done.add(resource)
        self._settle_not_applicable(walking)
        fetched: Dict[Tuple[str, str], Optional[str]] = {}  # (resource, id) -> failure, for this batch
        for position, work in enumerate(walking):
            for resource in sorted(work.pending):
                if _utcnow() >= ctx.deadline:
                    interruption: Optional[_Interruption] = _Interruption("stopped", "deadline", _utcnow())
                else:
                    key = targets[work.claim.key][resource]
                    interruption = self._fetch_one(ctx, work, bundle.FETCHERS[resource], key, fetched, run)
                if interruption:
                    self._end_run(run, interruption)
                    self._stop_walking(walking[position:], interruption)
                    return
            self._finish(work)

    def _targets(self, works: Sequence[_Work]) -> Dict[Tuple[str, str], Dict[str, str]]:
        """Per entry, the id each wanted resource is fetched by: the entry's own id, or for an item entry
        the user product / family of its stored row. A resource with no such id (the item has no user
        product, or was never stored) is settled here: nothing to fetch is not a failure. An own id the
        resource cannot hold (queue ids are not validated on enqueue) is charged to that entry alone."""
        linked = bundle.linked_ids(
            [
                w.claim.entity_id
                for w in works
                if w.claim.kind == ITEM_KIND and any(bundle.FETCHERS[r].entity != ITEM_KIND for r in w.plan.wanted)
            ]
        )
        targets: Dict[Tuple[str, str], Dict[str, str]] = {}
        for work in works:
            ids: Dict[str, str] = {}
            for resource in sorted(work.plan.wanted):
                entity = bundle.FETCHERS[resource].entity
                key = (
                    work.claim.entity_id
                    if entity == work.claim.kind
                    else linked.get(work.claim.entity_id, {}).get(entity)
                )
                if key is None:
                    self._skipped_not_applicable[resource] += 1
                    work.done.add(resource)
                elif not bundle.is_valid_key(resource, key):  # a hand-loaded id: fails this entry, not the batch
                    work.failed[resource] = f"invalid {entity} id"
                else:
                    ids[resource] = key
            targets[work.claim.key] = ids
        return targets

    def _settle_not_applicable(self, works: Sequence[_Work]) -> None:
        """Settle, uncharged, the pending resources that do not apply to their item (e.g. competition of a
        non-catalog listing): no request, no row. The item core of this run is already stored.
        Only item entries have item-entity resources: `item_signals` receives item ids only."""
        checked = [w for w in works if w.claim.kind == ITEM_KIND and w.pending & bundle.SIGNAL_RESOURCES]
        if not checked:
            return
        signals = bundle.item_signals([w.claim.entity_id for w in checked])
        for work in checked:
            known = signals.get(work.claim.entity_id)
            undecided = [
                r
                for r in sorted(work.pending & bundle.SIGNAL_RESOURCES)
                if known is None
                and not work.plan.needs_core
                and not bundle.is_applicable(r, known, explicit=work.plan.wanted[r])
            ]
            if undecided:
                # Named without its core and the item is not stored yet (its notification came first): whether it
                # applies is unknown, so its core goes first and the whole entry is refetched, never dropped. The
                # entry's other resources wait for that second pass instead of being fetched twice.
                self._requeue_core(work)
                work.done.update(work.pending)
                for resource in undecided:
                    self._requeued_for_core[resource] += 1
                continue
            for resource in sorted(work.pending & bundle.SIGNAL_RESOURCES):
                if not bundle.is_applicable(resource, known, explicit=work.plan.wanted[resource]):
                    work.done.add(resource)
                    self._skipped_not_applicable[resource] += 1

    @staticmethod
    def _requeue_core(work: _Work) -> None:
        """Queue the item's core on the claim's own lane. The bumped version makes the claim's completion keep
        the entry, so the next batch of the run fetches the core and then the named resource. That queue rule is
        pinned by `test_a_version_bump_while_claimed_keeps_the_entry_for_a_refetch` (test_queue.py)."""
        claim = work.claim
        entry = queue.EnqueueEntry(kind=claim.kind, entity_id=claim.entity_id, lane=claim.lane, resources=(CORE,))
        queue.enqueue([entry])

    def _due_resources(
        self,
        works: Sequence[_Work],
        targets: Dict[Tuple[str, str], Dict[str, str]],
        min_ages: Dict[str, Any],
        now: datetime,
    ) -> Dict[Tuple[str, str], Set[str]]:
        """Per entry, the wanted resources whose minimum age allows a fetch now."""
        checked: Dict[str, Dict[str, datetime]] = {}
        for resource in {name for w in works for name, explicit in w.plan.wanted.items() if not explicit}:
            if bundle.min_age_seconds(resource, min_ages) > 0:
                keys = [targets[w.claim.key][resource] for w in works if resource in targets[w.claim.key]]
                checked[resource] = bundle.last_checked(resource, keys)
        return {
            work.claim.key: {
                resource
                for resource, explicit in work.plan.wanted.items()
                if resource in targets[work.claim.key]
                and bundle.is_due(
                    explicit=explicit,
                    min_age=bundle.min_age_seconds(resource, min_ages),
                    last_checked_at=checked.get(resource, {}).get(targets[work.claim.key][resource]),
                    now=now,
                )
            }
            for work in works
        }

    def _fetch_one(
        self,
        ctx: WorkerContext,
        work: _Work,
        fetcher: bundle.SubFetcher,
        key: str,
        fetched: Dict[Tuple[str, str], Optional[str]],
        run: _Run,
    ) -> Optional[_Interruption]:
        """Fetch and store one sub-resource of one entry; returns an interruption that ends the run.

        `key` is the id the resource is fetched and stored by; `fetched` holds what this batch already
        fetched (resource, id) -> failure to charge, so entries sharing a user product or family fetch it
        once and share the outcome."""
        resource = fetcher.resource
        if (resource, key) in fetched:
            self._skipped_shared[resource] += 1
            self._settle(work, resource, fetched[(resource, key)])
            return None
        path, params = fetcher.request(key)
        run.called = True
        response = self._http().get(resource, path, params, deadline=ctx.deadline)
        interruption = self._interruption(response)
        if interruption:
            return interruption
        failure = self._store_one(resource, key, response)
        fetched[(resource, key)] = failure
        self._settle(work, resource, failure)
        return None

    def _store_one(self, resource: str, key: str, response: MlResponse) -> Optional[str]:
        """Apply one fetched response; returns the failure to charge to the resource, or None."""
        if response.error in (ERROR_TIMEOUT, ERROR_NETWORK, ERROR_INVALID_JSON):
            return response.error
        try:
            outcome = subresource_store.apply_subresource(
                RESOURCES[resource],
                (key,),
                response,
                counters=self._apply_counters,
                events_enabled=self._events_enabled,
            )
        except Exception as exc:  # noqa: BLE001 -- one resource's failure must not lose the others
            logger.exception("apply_subresource failed for %s %s", resource, key)
            return f"apply failed: {type(exc).__name__}: {exc}"[:300]
        self._sub_outcomes[resource][outcome.kind] += 1
        if outcome.kind == "error_recorded":
            return "malformed body" if 200 <= response.status < 300 else f"HTTP {response.status}"
        return None

    @staticmethod
    def _settle(work: _Work, resource: str, failure: Optional[str]) -> None:
        if failure:
            work.failed[resource] = failure
        else:
            work.done.add(resource)

    def _stop_walking(self, works: Sequence[_Work], interruption: _Interruption) -> None:
        """The run ended inside the sub-resource phase; `works[0]` is the entry being walked."""
        for work in works:
            if work.failed:
                # Failures already observed are real (a failed fetch of the entry being walked, or an id the
                # entry cannot be fetched by): charge them, keep what was not reached queued by name.
                self._finish(work, interrupted=True)
            elif not work.pending:  # everything was skipped by minimum age: nothing left to retry
                self._finish(work)
        self._release(works, interruption.not_before)

    # --- queue bookkeeping --------------------------------------------------------------

    def _finish(self, work: _Work, *, interrupted: bool = False) -> None:
        """Settle an entry: complete what succeeded, charge what failed, drop what cannot run."""
        claim, dropped = work.claim, set(work.plan.dropped)
        if work.core_error:
            succeeded, failed = dropped, {CORE: work.core_error}
        elif interrupted:
            # The core is applied; what was not reached stays queued by name beside the failures (the
            # entry is charged once, whatever the number of resources), never the bundle or the core.
            not_reached = {name: "not reached: run interrupted" for name in work.pending}
            succeeded, failed = set(claim.resources), {**not_reached, **work.failed}
        else:
            succeeded, failed = set(claim.resources), dict(work.failed)
        outcome = queue.complete(claim, succeeded=succeeded, failed=failed)
        work.settled = True
        if outcome != queue.OUTCOME_NOT_OWNER:
            for resource in dropped:
                self._dropped_counter(claim.kind, resource)[resource] += 1

    def _dropped_counter(self, kind: str, resource: str) -> Counter:
        """Why a dropped resource was dropped: not meant for this entry's entity, it has no fetcher yet, or it
        has one that is not enabled."""
        if not bundle.applies_to_kind(resource, kind):
            return self._skipped_not_applicable
        return self._skipped_disabled if bundle.has_fetcher(resource) else self._skipped_no_fetcher

    def _fail_core(self, works: Sequence[_Work], error: str, run: _Run) -> None:
        for work in works:
            run.failed += 1
            work.core_error = error
            self._finish(work)

    @staticmethod
    def _release(works: Sequence[_Work], not_before: datetime) -> None:
        """Give unsettled claims back uncharged; an entry whose core is done keeps only what is left."""
        unsettled = [w for w in works if not w.settled]
        pending = {
            w.claim.key: w.pending if w.core_status is not None or not w.plan.needs_core else set() for w in unsettled
        }
        queue.release([w.claim for w in unsettled], pending=pending, not_before=not_before)
        for work in unsettled:
            work.settled = True

    # --- counters -------------------------------------------------------------------------

    def _flush_counters(self, run: _Run) -> None:
        elements = {"200": 0, "404": 0, "failed": 0, **self._elements}
        counters = {
            "endpoints": self._client.counters.snapshot() if self._client else {},
            "elements": elements,
            "stale_discarded": self._apply_counters.stale_discarded,
            "noise_suppressed": sum(self._apply_counters.noise_suppressed.values()),
            "skipped_no_fetcher": dict(self._skipped_no_fetcher),
            "skipped_disabled": dict(self._skipped_disabled),
            "skipped_min_age": dict(self._skipped_min_age),
            "skipped_not_applicable": dict(self._skipped_not_applicable),
            "skipped_shared": dict(self._skipped_shared),
            "requeued_for_core": dict(self._requeued_for_core),
            "skipped_item_gone": self._skipped_item_gone,
            "subresources": {resource: dict(kinds) for resource, kinds in self._sub_outcomes.items()},
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


RELINK_HANDLER = "ml_publications.relink"
_RELINK_KEYS = ("links.enabled", "events.enabled")


def _relink_gate() -> Optional[bool]:
    """Read at every sweep batch boundary: the `events.enabled` flag while linking is on, else None (stop)."""
    config = settings_store.get_settings(_RELINK_KEYS)
    if config["links.enabled"].value is not True:
        return None
    return config["events.enabled"].value is True


class RelinkHandler:
    """`ml_publications.relink`: the product link re-link sweep (design D20). Makes no ML call.

    Every 15 minutes it evaluates units never evaluated or whose SKU key changed; when the product
    catalog fingerprint changed, and once a day after 04:30 (Argentina), it runs a forced lap that
    re-evaluates every unit. The daily pass lives inside this interval job: the scheduler gives a
    handler either an interval or a daily slot, never both, and no cron is introduced.
    """

    name = RELINK_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=15)
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        if _relink_gate() is None:
            return disabled_outcome()
        sweep = links.run_sweep(deadline=ctx.deadline, gate=_relink_gate)
        return JobResult(success=True, detail=sweep.as_detail())


SCAN_HANDLER = "ml_publications.scan"
_SCAN_KEYS = ("scan.enabled", "scan.statuses", "scan.next_mode", "rate_per_sec", "stock_rate_per_min")
ERROR_SELLER_NOT_CONFIGURED = "seller_not_configured"
# Failing runs of the same kind (ML errors, unexpected exceptions) with no good run in between, after
# which the scan stops retrying on every pass and waits for its daily slot; each failed run is retried
# on the next pass until then. The streak lives in the process (a restart clears it) and only failing
# runs extend it: a run cut short by the deadline or a 429 counts as a good one, so an outage that
# alternates 503 and 429 keeps retrying.
UPSTREAM_ERROR_STREAK = 5
# Engine errors that only a setup change can fix (`MlResponse.error` values of a call that was refused).
_BLOCKED_BY_SETUP = frozenset({OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN, "unauthorized"})


class ScanHandler:
    """`ml_publications.scan`: the daily lap over every seller status (design D17).

    Scheduled by the existing worker: a daily slot plus a 30 s catch-up that stays active while the
    persisted `worker_job_state.detail.complete` is False, so a lap that needs many runs (one run is
    bounded by the worker deadline) keeps going without any new scheduling machinery. A pending
    `scan.next_mode = full` makes the lap a backfill and is consumed when that lap completes.
    """

    name = SCAN_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = time(3, 30)
    catch_up_interval: Optional[timedelta] = timedelta(seconds=30)

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))
        self._client: Optional[MlHttpClient] = None
        self._error_streaks: Counter = Counter()  # consecutive failed runs of this process, per kind

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SCAN_KEYS)
        if config["scan.enabled"].value is not True:
            self._error_streaks.clear()
            return disabled_outcome()
        if not settings.ML_USER_ID:
            return self._blocked(ERROR_SELLER_NOT_CONFIGURED)
        self.pacer.configure(
            rate_per_sec=config["rate_per_sec"].value, stock_rate_per_min=config["stock_rate_per_min"].value
        )
        if self._client is None:
            self._client = self._client_factory(self.pacer)
        try:
            result = scans.run_scan(
                self._client,
                seller_id=str(settings.ML_USER_ID),
                statuses=config["scan.statuses"].value,
                requested_mode=config["scan.next_mode"].value,
                stale_days=settings.ML_PUB_STALE_DAYS,
                keep_going=lambda: settings_store.get_setting("scan.enabled").value is True,
                deadline=ctx.deadline,
            )
        except Exception as exc:  # noqa: BLE001 -- the worker must keep running; the lap resumes next run
            logger.exception("scan run failed")
            error = f"{type(exc).__name__}: {exc}"[:300]
            self._record_failure(error)
            return self._failed(error, reason="internal_error")
        if result.error in _BLOCKED_BY_SETUP:
            return self._blocked(result.error)
        if result.error:
            return self._failed(result.error, result.as_detail())
        self._error_streaks.clear()
        return JobResult(success=True, detail=self._flush(result.as_detail()))

    def _failed(
        self, error: str, detail: Optional[Dict[str, Any]] = None, *, reason: str = "upstream_error"
    ) -> JobResult:
        """A failed run is retried on the next pass; a streak of them means retrying will not help, so stop spinning."""
        self._error_streaks[reason] += 1
        if self._error_streaks[reason] >= UPSTREAM_ERROR_STREAK:
            self._error_streaks.clear()
            return self._blocked(reason)
        body = {**(detail or {"complete": False}), "error": error}
        return JobResult(success=False, detail=self._flush(body), error=error)

    def _blocked(self, reason: str) -> JobResult:
        """Nothing can run until something outside the scan changes: a missing seller or credentials, a
        rejected token (setup), or a sustained ML outage (`upstream_error`). Report a
        finished run (`complete` true, `blocked` names the reason) so the 30 s catch-up does not spin
        and the handler falls back to its daily slot; the open lap, if any, resumes from its stored
        progress on the next run.

        A pending operator request is consumed by this run (the runtime clears it on success); a
        `--mode full` request is not lost, since `scan.next_mode` stays, but running it now is: it
        starts at the next daily slot or on a new request once the setup is fixed."""
        self._error_streaks.clear()
        logger.error("scan blocked: %s", reason)
        return JobResult(success=True, detail=self._flush({"complete": True, "blocked": reason}))

    @staticmethod
    def _record_failure(error: str) -> None:
        try:
            scans.record_failure(error)
        except Exception:  # noqa: BLE001 -- observability must never fail a run
            logger.exception("could not record the scan failure")

    def _flush(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        detail = {**detail, "at": _utcnow().isoformat()}
        _persist_detail(self.name, detail)
        return detail


MISSED_FEEDS_HANDLER = "ml_publications.missed_feeds"
_MISSED_FEEDS_KEYS = ("missed_feeds.enabled", "intake.topics", "rate_per_sec", "stock_rate_per_min")
ERROR_CLIENT_NOT_CONFIGURED = "client_not_configured"
# A failed run waits before the next try, doubling from a minute up to an hour: the interval job would
# otherwise be due again on every pass (a handler that fails is never marked as having succeeded).
MISSED_FEEDS_RETRY_BASE = timedelta(seconds=60)
MISSED_FEEDS_RETRY_CAP = timedelta(hours=1)


def missed_feeds_retry_delay(failures: int) -> timedelta:
    """How long to wait after the `failures`-th consecutive failed run (1 -> 60 s, 2 -> 120 s, ... capped)."""
    return min(MISSED_FEEDS_RETRY_BASE * 2 ** max(failures - 1, 0), MISSED_FEEDS_RETRY_CAP)


def _read_detail(name: str) -> Dict[str, Any]:
    try:
        with database.get_background_db() as db:
            found = db.execute(text("SELECT detail FROM worker_job_state WHERE name = :name"), {"name": name}).scalar()
    except Exception:  # noqa: BLE001 -- an unreadable state only costs a restart from the first page
        logger.exception("could not read %s state", name)
        return {}
    return found if isinstance(found, dict) else {}


class MissedFeedsHandler:
    """`ml_publications.missed_feeds`: recovers notifications ML could not deliver (design D17).

    Scheduled by the existing worker every 2 hours (ML keeps missed feeds for 2 days). A run that does not
    finish (worker deadline, flag turned off, 429, failure) persists its position in
    `worker_job_state.detail.resume` and the next run continues there; a failed run waits
    `missed_feeds_retry_delay(failures)` before the next try. Every execution leaves an `ml_pub_job_runs` row.
    """

    name = MISSED_FEEDS_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(hours=2)
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

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_MISSED_FEEDS_KEYS)
        if config["missed_feeds.enabled"].value is not True:
            return disabled_outcome()
        state = _read_detail(self.name)
        if not settings.ML_USER_ID:
            return self._blocked(ERROR_SELLER_NOT_CONFIGURED, state)
        if not settings.ML_CLIENT_ID:
            return self._blocked(ERROR_CLIENT_NOT_CONFIGURED, state)
        retry_at = _parse_moment(state.get("retry_at"))
        if retry_at is not None and _utcnow() < retry_at:
            return JobResult(success=False, detail={"backoff_until": retry_at.isoformat()})
        mappings = intake_core.topic_mappings(config["intake.topics"].value)
        self.pacer.configure(
            rate_per_sec=config["rate_per_sec"].value, stock_rate_per_min=config["stock_rate_per_min"].value
        )
        if self._client is None:
            self._client = self._client_factory(self.pacer)
        result = missed_feeds_core.run_missed_feeds(
            self._client,
            seller_id=str(settings.ML_USER_ID),
            app_id=str(settings.ML_CLIENT_ID),
            mappings=mappings,
            keep_going=lambda: settings_store.get_setting("missed_feeds.enabled").value is True,
            deadline=ctx.deadline,
            resume=state.get("resume"),
        )
        error = result.error
        if error in _BLOCKED_BY_SETUP or error == "http_401":
            return self._blocked("unauthorized" if error == "http_401" else str(error), state)
        failures = int(state.get("failures") or 0)
        retry: Optional[datetime] = None
        if error:
            failures += 1
            retry = _utcnow() + missed_feeds_retry_delay(failures)
        elif result.complete:
            failures = 0
        elif result.stopped == missed_feeds_core.STOP_RATE_LIMITED:
            retry = _utcnow() + MISSED_FEEDS_RETRY_BASE  # waiting out a 429 is not a failure
        detail = self._flush(result.as_detail(), failures=failures, retry_at=retry, resume=result.resume)
        return JobResult(success=result.complete, detail=detail, error=error)

    def _blocked(self, reason: str, state: Dict[str, Any]) -> JobResult:
        """Nothing can run until setup changes: report a finished run so the handler waits for its next
        interval instead of spinning; a stored resume position is kept for when it is fixed."""
        logger.error("missed feeds blocked: %s", reason)
        detail = self._flush(
            {"complete": True, "blocked": reason}, failures=0, retry_at=None, resume=state.get("resume")
        )
        return JobResult(success=True, detail=detail)

    def _flush(
        self, detail: Dict[str, Any], *, failures: int, retry_at: Optional[datetime], resume: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        detail = {
            **detail,
            "failures": failures,
            "retry_at": retry_at.isoformat() if retry_at else None,
            "resume": resume,
            "counters": self._client.counters.snapshot() if self._client is not None else {},
            "at": _utcnow().isoformat(),
        }
        _persist_detail(self.name, detail)
        return detail


def _parse_moment(value: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return moment if moment is None or moment.tzinfo else moment.replace(tzinfo=timezone.utc)


SWEEP_HANDLER = "ml_publications.sweep"
_SWEEP_KEYS = ("sweep.enabled", "sweep.statuses", "bundle_resources")


class SweepHandler:
    """`ml_publications.sweep`: performance and visits have no notification topic, so every 10 minutes
    this tick enqueues the oldest `ceil(eligible / 144)` items of each in the sweep lane (design D17).

    It makes NO ML call and holds no pacer: the refresh handler fetches what it enqueues, under the shared
    budget and the lane order, and the tick itself yields while live work is waiting. A tick that fails is
    recorded and simply followed by the next one, ten minutes later.
    """

    name = SWEEP_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=10)
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SWEEP_KEYS)
        if config["sweep.enabled"].value is not True:
            return disabled_outcome()
        result = sweeps_core.run_sweep(
            statuses=sweeps_core.sweep_statuses(config["sweep.statuses"].value),
            bundle_resources=config["bundle_resources"].value,
            recheck_days=settings.ML_PUB_NOT_APPLICABLE_RECHECK_DAYS,
        )
        detail = {**result.as_detail(), "at": _utcnow().isoformat()}
        _persist_detail(self.name, detail)
        return JobResult(success=True, detail=detail, error=result.error)


refresh = RefreshHandler()
intake = IntakeHandler()
relink = RelinkHandler()
scan = ScanHandler(pacer=refresh.pacer)  # one in-process ML budget for every call the store makes
missed_feeds = MissedFeedsHandler(pacer=refresh.pacer)
sweep = SweepHandler()
