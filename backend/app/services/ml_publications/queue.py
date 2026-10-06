"""Durable dirty queue of resources to refresh (design D10).

Postgres only (`FOR UPDATE SKIP LOCKED`, `gen_random_uuid()`, array merging).
Every function runs in its OWN short transaction through `get_background_db()`
-- never a session the caller holds -- so no transaction spans an ML call.

Lifecycle of an entry, keyed `(kind, entity_id)`:

- `enqueue` is idempotent and collapses repeats: resources are merged, the lane
  only ever moves to a higher priority, `version` is bumped.
- `claim` hands out entries single-flight (`SKIP LOCKED`) under a fresh
  `claim_token`; a claim older than the lease is charged one attempt and becomes
  claimable again (crash recovery).
- `complete` / `release` / `park` are all fenced by the claim token, so a worker
  whose lease expired can never touch an entry another worker owns.

This module deletes rows only from `ml_pub_refresh_queue`, and only in `complete`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import text

from app.core import database
from app.core.config import settings

# Lanes, highest priority first.
LANE_MANUAL = 0
LANE_NOTIFICATION = 1
LANE_RECONCILE = 2
LANE_BACKFILL = 3
LANE_SWEEP = 4

BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 6 * 3600.0
MAX_ERROR_CHARS = 1000

OUTCOME_COMPLETED = "completed"
OUTCOME_REQUEUED = "requeued"
OUTCOME_PARTIAL = "partial"
OUTCOME_FAILED = "failed"
OUTCOME_PARKED = "parked"
OUTCOME_NOT_OWNER = "not_owner"


@dataclass(frozen=True)
class EnqueueEntry:
    kind: str
    entity_id: str
    lane: int
    resources: Tuple[str, ...] = ("bundle",)
    source_received_at: Optional[datetime] = None
    not_before: Optional[datetime] = None


@dataclass(frozen=True)
class QueueClaim:
    kind: str
    entity_id: str
    resources: Tuple[str, ...]
    lane: int
    version: int
    claim_token: str
    attempts: int
    source_received_at: Optional[datetime]

    @property
    def key(self) -> Tuple[str, str]:
        return (self.kind, self.entity_id)


class LaneFairness:
    """Every Nth claim batch serves the LOWEST-priority lanes first, so backfill and
    sweeps are never starved while live lanes keep priority in the other batches."""

    def __init__(self, low_lane_min_share: float) -> None:
        if not 0 < low_lane_min_share <= 1:
            raise ValueError("low_lane_min_share must be in (0, 1]")
        self._period = max(1, round(1 / low_lane_min_share))
        self._calls = 0

    def next_lanes_desc(self) -> bool:
        self._calls += 1
        return self._calls % self._period == 0


_ENQUEUE_SQL = text(
    """
    INSERT INTO ml_pub_refresh_queue AS q
        (kind, entity_id, resources, lane, source_received_at, not_before)
    VALUES (:kind, :entity_id, CAST(:resources AS text[]), :lane, :source_received_at, COALESCE(:not_before, now()))
    ON CONFLICT (kind, entity_id) DO UPDATE SET
        resources = ARRAY(SELECT x FROM unnest(q.resources || EXCLUDED.resources) AS x GROUP BY x ORDER BY x),
        lane = LEAST(q.lane, EXCLUDED.lane),
        version = q.version + 1,
        last_enqueued_at = now(),
        source_received_at = LEAST(q.source_received_at, EXCLUDED.source_received_at),
        not_before = CASE WHEN EXCLUDED.lane < q.lane THEN LEAST(q.not_before, EXCLUDED.not_before)
                          ELSE q.not_before END,
        parked_at = CASE WHEN EXCLUDED.lane = 0 THEN NULL ELSE q.parked_at END,
        attempts = CASE WHEN EXCLUDED.lane = 0 THEN 0 ELSE q.attempts END
    """
)


def enqueue(entries: Sequence[EnqueueEntry]) -> int:
    """Idempotent upsert of `entries` in one transaction. Returns the number of entries submitted."""
    if not entries:
        return 0
    params = [
        {
            "kind": e.kind,
            "entity_id": e.entity_id,
            "resources": sorted(set(e.resources)),
            "lane": e.lane,
            "source_received_at": e.source_received_at,
            "not_before": e.not_before,
        }
        for e in entries
    ]
    with database.get_background_db() as session:
        session.execute(_ENQUEUE_SQL, params)
    return len(entries)


_CHARGE_EXPIRED_SQL = text(
    """
    UPDATE ml_pub_refresh_queue q
    SET attempts = q.attempts + 1,
        last_error = 'lease_expired',
        claimed_at = NULL, claimed_by = NULL, claim_token = NULL,
        parked_at = CASE WHEN q.attempts + 1 >= :max_attempts THEN now() ELSE q.parked_at END
    FROM (
        SELECT kind, entity_id FROM ml_pub_refresh_queue
        WHERE claimed_at IS NOT NULL AND claimed_at < now() - (:lease_seconds * interval '1 second')
        FOR UPDATE SKIP LOCKED
    ) expired
    WHERE q.kind = expired.kind AND q.entity_id = expired.entity_id
    """
)

_CLAIM_SQL = """
    UPDATE ml_pub_refresh_queue q
    SET claimed_at = now(), claimed_by = :worker_id, claim_token = gen_random_uuid()
    FROM (
        SELECT kind, entity_id FROM ml_pub_refresh_queue
        WHERE claimed_at IS NULL AND parked_at IS NULL AND not_before <= now()
          AND kind = ANY(CAST(:kinds AS text[]))
        ORDER BY {lane_order}, not_before, first_enqueued_at
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    ) c
    WHERE q.kind = c.kind AND q.entity_id = c.entity_id
    RETURNING q.kind, q.entity_id, q.resources, q.lane, q.version, q.claim_token, q.attempts,
              q.source_received_at, q.not_before, q.first_enqueued_at
"""


def claim(
    *,
    limit: int,
    worker_id: str,
    kinds: Sequence[str],
    lanes_desc: bool = False,
    lease_seconds: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> List[QueueClaim]:
    """Charge expired leases, then claim up to `limit` ready entries for `worker_id`.

    `lanes_desc` serves the lowest-priority lane first (see `LaneFairness`)."""
    lease = settings.ML_PUB_LEASE_SECONDS if lease_seconds is None else lease_seconds
    max_attempts = settings.ML_PUB_MAX_ATTEMPTS if max_attempts is None else max_attempts
    statement = text(_CLAIM_SQL.format(lane_order="lane DESC" if lanes_desc else "lane"))
    with database.get_background_db() as session:
        session.execute(_CHARGE_EXPIRED_SQL, {"lease_seconds": lease, "max_attempts": max_attempts})
        rows = session.execute(statement, {"worker_id": worker_id, "kinds": list(kinds), "limit": limit}).fetchall()
    ordered = sorted(rows, key=lambda r: (-r.lane if lanes_desc else r.lane, r.not_before, r.first_enqueued_at))
    return [
        QueueClaim(
            kind=r.kind,
            entity_id=r.entity_id,
            resources=tuple(sorted(r.resources)),
            lane=r.lane,
            version=r.version,
            claim_token=str(r.claim_token),
            attempts=r.attempts,
            source_received_at=r.source_received_at,
        )
        for r in ordered
    ]


_LOCK_OWNED_SQL = text(
    """
    SELECT version, resources, attempts FROM ml_pub_refresh_queue
    WHERE kind = :kind AND entity_id = :entity_id AND claim_token = CAST(:token AS uuid)
    FOR UPDATE
    """
)

_UPDATE_OWNED_SQL = """
    UPDATE ml_pub_refresh_queue SET {assignments}
    WHERE kind = :kind AND entity_id = :entity_id AND claim_token = CAST(:token AS uuid)
"""

_CLEAR_CLAIM = "claimed_at = NULL, claimed_by = NULL, claim_token = NULL"


def _owned_params(claim_: QueueClaim, **extra: object) -> Dict[str, object]:
    return {"kind": claim_.kind, "entity_id": claim_.entity_id, "token": claim_.claim_token, **extra}


def _backoff_seconds(attempts: int, rng: random.Random) -> float:
    return min(BACKOFF_BASE_SECONDS * 2.0**attempts, BACKOFF_CAP_SECONDS) * rng.uniform(0.5, 1.0)


def _format_errors(failed: Mapping[str, str]) -> str:
    return "; ".join(f"{resource}: {error}" for resource, error in sorted(failed.items()))[:MAX_ERROR_CHARS]


def complete(
    claim_: QueueClaim,
    *,
    succeeded: Set[str],
    failed: Mapping[str, str],
    max_attempts: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> str:
    """Record the result of one claimed entry, fenced by its claim token.

    - failures: the entry keeps only the failed resources, is charged one attempt
      and backed off; at `max_attempts` it is parked;
    - a notification landed meanwhile (`version` moved): the claim is cleared and the
      merged resources kept so the entry is refetched;
    - everything succeeded and the version is unchanged: the entry is deleted;
    - some requested resources were not reported: they stay queued, uncharged.
    """
    max_attempts = settings.ML_PUB_MAX_ATTEMPTS if max_attempts is None else max_attempts
    rng = rng or random.Random()
    with database.get_background_db() as session:
        owned = session.execute(_LOCK_OWNED_SQL, _owned_params(claim_)).first()
        if owned is None:
            return OUTCOME_NOT_OWNER
        remaining = (set(owned.resources) - set(succeeded)) | set(failed)
        if failed:
            attempts = owned.attempts + 1
            parked = attempts >= max_attempts
            session.execute(
                text(
                    _UPDATE_OWNED_SQL.format(
                        assignments=f"resources = CAST(:resources AS text[]), attempts = :attempts, "
                        f"last_error = :error, not_before = now() + (:delay * interval '1 second'), "
                        f"parked_at = CASE WHEN :parked THEN now() ELSE parked_at END, {_CLEAR_CLAIM}"
                    )
                ),
                _owned_params(
                    claim_,
                    resources=sorted(remaining),
                    attempts=attempts,
                    error=_format_errors(failed),
                    delay=_backoff_seconds(attempts, rng),
                    parked=parked,
                ),
            )
            return OUTCOME_PARKED if parked else OUTCOME_FAILED
        if owned.version != claim_.version:
            session.execute(text(_UPDATE_OWNED_SQL.format(assignments=_CLEAR_CLAIM)), _owned_params(claim_))
            return OUTCOME_REQUEUED
        if not remaining:
            session.execute(
                text(
                    "DELETE FROM ml_pub_refresh_queue "
                    "WHERE kind = :kind AND entity_id = :entity_id AND claim_token = CAST(:token AS uuid)"
                ),
                _owned_params(claim_),
            )
            return OUTCOME_COMPLETED
        session.execute(
            text(_UPDATE_OWNED_SQL.format(assignments=f"resources = CAST(:resources AS text[]), {_CLEAR_CLAIM}")),
            _owned_params(claim_, resources=sorted(remaining)),
        )
        return OUTCOME_PARTIAL


def release(
    claims: Sequence[QueueClaim],
    *,
    pending: Mapping[Tuple[str, str], Set[str]],
    not_before: datetime,
) -> None:
    """Give claims back UNCHARGED (429 cooldown, deadline), delayed until `not_before`.

    `pending` may narrow an entry's resources to what is still to do; the narrowing is
    skipped when a notification bumped the version meanwhile, so nothing newer is lost."""
    if not claims:
        return
    statement = text(
        _UPDATE_OWNED_SQL.format(
            assignments=f"not_before = :not_before, "
            f"resources = CASE WHEN :narrow AND version = :version THEN CAST(:resources AS text[]) "
            f"ELSE resources END, {_CLEAR_CLAIM}"
        )
    )
    with database.get_background_db() as session:
        for claim_ in claims:
            still = pending.get(claim_.key) or set()
            session.execute(
                statement,
                _owned_params(
                    claim_,
                    not_before=not_before,
                    narrow=bool(still),
                    version=claim_.version,
                    resources=sorted(still),
                ),
            )


def park(claim_: QueueClaim, error: str) -> bool:
    """Take a claimed entry out of circulation (visible, never deleted). Fenced by the token."""
    with database.get_background_db() as session:
        result = session.execute(
            text(
                _UPDATE_OWNED_SQL.format(
                    assignments=f"parked_at = now(), last_error = :error, {_CLEAR_CLAIM}",
                )
            ),
            _owned_params(claim_, error=error[:MAX_ERROR_CHARS]),
        )
    return result.rowcount == 1
