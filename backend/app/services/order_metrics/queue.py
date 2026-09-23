"""Claim / fenced-store / release primitives over `ml_order_metrics_dirty`
(ventas-ml-rediseno PR3, design D5). Postgres-only (`FOR UPDATE SKIP
LOCKED`, `claim_token = ANY(uuid[])`); every write here runs in its OWN
short transaction via `get_background_db()` -- never a session the caller
passes in, and never one long transaction for a whole batch (design D5
rev 6: "the store phase is one short transaction per order").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Sequence

from sqlalchemy import text

from app.core.database import get_background_db
from app.services.order_metrics.store import store_order_metrics
from app.services.order_metrics.types import OrderMetrics

# `attempts >= POISON_THRESHOLD` parks an order: excluded from claim,
# counted by `poisoned_count` (design D5 "Attempts rule").
POISON_THRESHOLD = 5


@dataclass(frozen=True)
class Claim:
    order_id: int
    version: int
    claim_token: uuid.UUID
    attempts: int


@dataclass(frozen=True)
class FencedResult:
    """Outcome of one `fenced_store` call, one entry per input claim."""

    stored_order_ids: List[int] = field(default_factory=list)
    """Fence held, version unchanged: metrics upserted, dirty row deleted."""

    unclaimed_order_ids: List[int] = field(default_factory=list)
    """Fence held, version CHANGED (an input write landed meanwhile):
    metrics upserted from the snapshot this worker computed, but the dirty
    row survives, claim columns cleared, so the next pass re-claims it
    (design D5 rev 3 "no lost update")."""

    not_owner_order_ids: List[int] = field(default_factory=list)
    """No row matched `order_id AND claim_token`: this worker's lease
    expired and was reclaimed, or the row is gone -- nothing written."""

    skipped_order_ids: List[int] = field(default_factory=list)
    """No entry in `metrics` for this claim (the bulk compute phase did not
    return it) -- left untouched, dirty row unmodified, retried next pass."""


def claim_dirty(*, limit: int, lease: timedelta, worker_id: str) -> List[Claim]:
    """Charges expired leases, then claims up to `limit` dirty rows this
    worker now owns (design D5 step 1), in its own short transaction (never
    a session the caller passes in -- deviation from the design's literal
    `db: Session` first arg, same shape `HeartbeatThread` already uses).
    A row with `attempts > 0` OR `suspect` is claimed ALONE, in its own
    singleton pass, before the normal batch -- so a process-killing order
    isolates itself instead of poisoning its batch-mates (design D5
    "Attempts rule")."""
    claims: List[Claim] = []
    with get_background_db() as session:
        session.execute(
            text(
                """
                UPDATE ml_order_metrics_dirty d
                SET attempts = d.attempts + 1,
                    last_error = 'lease_expired',
                    claimed_at = NULL,
                    claimed_by = NULL,
                    claim_token = NULL
                FROM (
                    SELECT order_id FROM ml_order_metrics_dirty
                    WHERE claimed_at IS NOT NULL
                      AND claimed_at < now() - (:lease_seconds * interval '1 second')
                    FOR UPDATE SKIP LOCKED
                ) expired
                WHERE d.order_id = expired.order_id
                """
            ),
            {"lease_seconds": lease.total_seconds()},
        )

        # Singleton pass first: rows with attempts > 0 or suspect are
        # claimed one at a time, isolated from a fresh batch.
        singleton_row = session.execute(
            text(
                """
                UPDATE ml_order_metrics_dirty d
                SET claimed_at = now(), claimed_by = :worker_id, claim_token = gen_random_uuid()
                FROM (
                    SELECT order_id FROM ml_order_metrics_dirty
                    WHERE claimed_at IS NULL AND attempts < :poison_threshold AND (attempts > 0 OR suspect)
                    ORDER BY enqueued_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                ) c
                WHERE d.order_id = c.order_id
                RETURNING d.order_id, d.version, d.claim_token, d.attempts
                """
            ),
            {"worker_id": worker_id, "poison_threshold": POISON_THRESHOLD},
        ).fetchone()
        if singleton_row is not None:
            claims.append(
                Claim(
                    order_id=singleton_row[0],
                    version=singleton_row[1],
                    claim_token=singleton_row[2],
                    attempts=singleton_row[3],
                )
            )
        else:
            remaining = limit
            if remaining > 0:
                batch_rows = session.execute(
                    text(
                        """
                        UPDATE ml_order_metrics_dirty d
                        SET claimed_at = now(), claimed_by = :worker_id, claim_token = gen_random_uuid()
                        FROM (
                            SELECT order_id FROM ml_order_metrics_dirty
                            WHERE claimed_at IS NULL AND attempts = 0 AND NOT suspect
                            ORDER BY enqueued_at
                            LIMIT :limit
                            FOR UPDATE SKIP LOCKED
                        ) c
                        WHERE d.order_id = c.order_id
                        RETURNING d.order_id, d.version, d.claim_token, d.attempts
                        """
                    ),
                    {"worker_id": worker_id, "limit": remaining},
                ).fetchall()
                claims.extend(
                    Claim(order_id=row[0], version=row[1], claim_token=row[2], attempts=row[3]) for row in batch_rows
                )
    return claims


def fenced_store(claims: Sequence[Claim], metrics: Dict[int, OrderMetrics]) -> FencedResult:
    """Per-order fenced store (design D5 step 2b, rev 6): one SHORT
    transaction PER order, never a batch-wide one, so a writer's trigger
    upsert or the heartbeat's lease renewal never waits behind the rest of
    the batch. For each claim: `SELECT version ... FOR UPDATE` on the row
    matching `order_id AND claim_token`. No row -> not this worker's claim
    anymore, nothing written. Row found -> store, then delete (version
    unchanged) or unclaim (version changed, an input write landed --
    design D5 rev 3 fence, no lost update)."""
    result = FencedResult()
    for claim in claims:
        order_metrics = metrics.get(claim.order_id)
        if order_metrics is None:
            result.skipped_order_ids.append(claim.order_id)
            continue

        with get_background_db() as session:
            row = session.execute(
                text(
                    "SELECT version FROM ml_order_metrics_dirty "
                    "WHERE order_id = :order_id AND claim_token = :claim_token FOR UPDATE"
                ),
                {"order_id": claim.order_id, "claim_token": str(claim.claim_token)},
            ).fetchone()
            if row is None:
                result.not_owner_order_ids.append(claim.order_id)
                continue

            current_version = row[0]
            store_order_metrics(session, {claim.order_id: order_metrics})

            if current_version == claim.version:
                session.execute(
                    text(
                        "DELETE FROM ml_order_metrics_dirty WHERE order_id = :order_id AND claim_token = :claim_token"
                    ),
                    {"order_id": claim.order_id, "claim_token": str(claim.claim_token)},
                )
                result.stored_order_ids.append(claim.order_id)
            else:
                session.execute(
                    text(
                        "UPDATE ml_order_metrics_dirty SET claimed_at = NULL, claimed_by = NULL, claim_token = NULL "
                        "WHERE order_id = :order_id AND claim_token = :claim_token"
                    ),
                    {"order_id": claim.order_id, "claim_token": str(claim.claim_token)},
                )
                result.unclaimed_order_ids.append(claim.order_id)
    return result


def mark_failed(claim: Claim, error: str) -> None:
    """Charges one failed attempt to `claim` (design D5 "Failure"): an
    exception attributable to exactly this order (its own store
    transaction, or a compute step run alone for it). Fenced by
    `claim_token` -- a claim already reclaimed by another worker is left
    alone (that worker owns the charge, if any, for its own attempt)."""
    with get_background_db() as session:
        session.execute(
            text(
                """
                UPDATE ml_order_metrics_dirty
                SET attempts = attempts + 1, last_error = :error,
                    claimed_at = NULL, claimed_by = NULL, claim_token = NULL
                WHERE order_id = :order_id AND claim_token = :claim_token
                """
            ),
            {"order_id": claim.order_id, "claim_token": str(claim.claim_token), "error": error},
        )


def release_uncharged(claims: Sequence[Claim], *, suspect: bool = False) -> None:
    """Batch-timeout / deadline release (design D5): clears the claim
    columns of every `claims` entry WITHOUT charging an attempt. `suspect`
    marks them for a durable singleton retry (never re-enters a full batch,
    survives a worker restart) -- used by a `BatchTimeout` in the COMPUTE
    phase. A deadline reached mid-STORE releases only the unstored orders,
    NOT suspect (their compute already succeeded, nothing is wrong with
    them -- design D5 rev 6)."""
    if not claims:
        return
    tokens = [str(claim.claim_token) for claim in claims]
    with get_background_db() as session:
        session.execute(
            text(
                """
                UPDATE ml_order_metrics_dirty
                SET claimed_at = NULL, claimed_by = NULL, claim_token = NULL, suspect = :suspect
                WHERE claim_token = ANY(CAST(:tokens AS uuid[]))
                """
            ),
            {"tokens": tokens, "suspect": suspect},
        )


def renew_leases(*, worker_id: str, tokens: Sequence[str]) -> int:
    """Renews `claimed_at` for every dirty row `worker_id` still holds,
    fenced by `claim_token` -- the same statement `HeartbeatThread._tick`
    already runs each tick (design D4 step 5); exposed here as the
    `order_metrics.queue` public primitive the design interface names, so
    a caller other than the heartbeat thread can also invoke it."""
    tokens = list(tokens)
    if not tokens:
        return 0
    with get_background_db() as session:
        result = session.execute(
            text(
                "UPDATE ml_order_metrics_dirty SET claimed_at = now() "
                "WHERE claimed_by = :worker_id AND claim_token = ANY(CAST(:tokens AS uuid[]))"
            ),
            {"worker_id": worker_id, "tokens": tokens},
        )
        return result.rowcount


def poisoned_count(db) -> int:
    """Count of parked orders (`attempts >= POISON_THRESHOLD`), reused by
    the PR6 health endpoint (design D9)."""
    row = db.execute(
        text("SELECT count(*) FROM ml_order_metrics_dirty WHERE attempts >= :threshold"),
        {"threshold": POISON_THRESHOLD},
    ).fetchone()
    return int(row[0]) if row else 0
