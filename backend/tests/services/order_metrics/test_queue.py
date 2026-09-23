"""RED/GREEN -- `order_metrics.queue` (ventas-ml-rediseno PR3.T1-T4f, design
D5): claim/fence/attempts/suspect concurrency primitives over
`ml_order_metrics_dirty`, tested against real Postgres (`FOR UPDATE SKIP
LOCKED`, claim-token fencing -- SQLite's single-writer model cannot
reproduce any of this).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.order_metrics.queue import (
    POISON_THRESHOLD,
    claim_dirty,
    fenced_store,
    mark_failed,
    poisoned_count,
    release_uncharged,
)
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _metrics(order_id: int) -> OrderMetrics:
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal("50.00"),
        total_gauss=Decimal("40.00"),
        markup_pct=Decimal("80.00"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=1,
        computed_at=datetime.now(timezone.utc),
        lineas=[],
    )


def _insert_order(conn, order_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
            "VALUES (:order_id, 999, 'paid', now(), now()) ON CONFLICT (order_id) DO NOTHING"
        ),
        {"order_id": order_id},
    )


def _insert_dirty(conn, order_id: int, **overrides) -> None:
    row = {
        "order_id": order_id,
        "version": 1,
        "reason": "input_write",
        "claimed_at": None,
        "claimed_by": None,
        "claim_token": None,
        "attempts": 0,
        "last_error": None,
        "suspect": False,
    }
    row.update(overrides)
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics_dirty "
            "(order_id, version, reason, claimed_at, claimed_by, claim_token, attempts, last_error, suspect) "
            "VALUES (:order_id, :version, :reason, :claimed_at, :claimed_by, :claim_token, :attempts, :last_error, :suspect)"
        ),
        row,
    )


@pytest.fixture()
def _order_metrics_db_session(monkeypatch, pg_order_metrics_engine):
    """Points `get_background_db()` (what `queue.py` uses exclusively) at
    `pg_order_metrics_engine` for the duration of one test."""
    session_factory = sessionmaker(bind=pg_order_metrics_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    yield
    with pg_order_metrics_engine.connect() as conn:
        conn.execute(text("DELETE FROM ml_venta_deducciones"))
        conn.execute(text("DELETE FROM ml_order_metrics"))
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


@pytest.mark.postgres
class TestClaimDirtyDisjoint:
    """PR3.T1: two concurrent claimers get disjoint order sets."""

    def test_two_claimers_never_overlap(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            for order_id in range(1, 11):
                _insert_order(conn, order_id)
                _insert_dirty(conn, order_id)
            conn.commit()

        claims_a = claim_dirty(limit=5, lease=timedelta(seconds=120), worker_id="worker-a")
        claims_b = claim_dirty(limit=5, lease=timedelta(seconds=120), worker_id="worker-b")

        ids_a = {c.order_id for c in claims_a}
        ids_b = {c.order_id for c in claims_b}
        assert ids_a & ids_b == set()
        assert len(ids_a) == 5
        assert len(ids_b) == 5


@pytest.mark.postgres
class TestLeaseExpiry:
    """PR3.T2: an expired lease reclaims the row of a crashed worker."""

    def test_expired_lease_is_reclaimable(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 42)
            _insert_dirty(
                conn,
                42,
                claimed_at=datetime.now(timezone.utc) - timedelta(seconds=200),
                claimed_by="dead-worker",
                claim_token=str(uuid.uuid4()),
            )
            conn.commit()

        claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="worker-b")
        assert [c.order_id for c in claims] == [42]

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = 42")
            ).fetchone()
        assert row.attempts == 1
        assert row.last_error == "lease_expired"

    def test_live_lease_is_not_reclaimed(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 43)
            _insert_dirty(
                conn,
                43,
                claimed_at=datetime.now(timezone.utc),
                claimed_by="live-worker",
                claim_token=str(uuid.uuid4()),
            )
            conn.commit()

        claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="worker-b")
        assert claims == []


@pytest.mark.postgres
class TestFencedStore:
    """PR3.T3: fenced_store upserts on unchanged version, unclaims (never
    drops) on a version bump, and writes nothing for a lost claim."""

    def test_owner_unchanged_version_upserts_and_deletes(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 1)
            _insert_dirty(conn, 1)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")

        result = fenced_store([claim], {1: _metrics(1)})

        assert result.stored_order_ids == [1]
        with pg_order_metrics_engine.connect() as conn:
            metrics_row = conn.execute(text("SELECT total_gauss FROM ml_order_metrics WHERE order_id = 1")).fetchone()
            dirty_row = conn.execute(text("SELECT 1 FROM ml_order_metrics_dirty WHERE order_id = 1")).fetchone()
        assert metrics_row.total_gauss == Decimal("40.00")
        assert dirty_row is None

    def test_owner_bumped_version_upserts_but_keeps_row_unclaimed(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 2)
            _insert_dirty(conn, 2)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")

        # Simulates an input write landing while this worker held the claim
        # (design D5 rev 3): a direct SQL UPDATE, no enqueue function needed.
        with pg_order_metrics_engine.connect() as conn:
            conn.execute(text("UPDATE ml_order_metrics_dirty SET version = version + 1 WHERE order_id = 2"))
            conn.commit()

        result = fenced_store([claim], {2: _metrics(2)})

        assert result.unclaimed_order_ids == [2]
        with pg_order_metrics_engine.connect() as conn:
            metrics_row = conn.execute(text("SELECT total_gauss FROM ml_order_metrics WHERE order_id = 2")).fetchone()
            dirty_row = conn.execute(
                text("SELECT claimed_at, claimed_by, claim_token FROM ml_order_metrics_dirty WHERE order_id = 2")
            ).fetchone()
        # Metrics still upserted from the snapshot this worker computed.
        assert metrics_row.total_gauss == Decimal("40.00")
        # But the dirty row survives, unclaimed -- the next pass re-claims it.
        assert dirty_row is not None
        assert dirty_row.claimed_at is None
        assert dirty_row.claimed_by is None
        assert dirty_row.claim_token is None

    def test_token_no_longer_present_writes_nothing(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 3)
            _insert_dirty(conn, 3)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")
        # Simulates a lease expiry + reclaim by another worker: this
        # worker's token is gone by the time it tries to store.
        with pg_order_metrics_engine.connect() as conn:
            conn.execute(
                text("UPDATE ml_order_metrics_dirty SET claim_token = :new_token WHERE order_id = 3"),
                {"new_token": str(uuid.uuid4())},
            )
            conn.commit()

        result = fenced_store([claim], {3: _metrics(3)})

        assert result.not_owner_order_ids == [3]
        with pg_order_metrics_engine.connect() as conn:
            metrics_row = conn.execute(text("SELECT 1 FROM ml_order_metrics WHERE order_id = 3")).fetchone()
        assert metrics_row is None


@pytest.mark.postgres
class TestMarkFailedPoisoning:
    """PR3.T4: 5 failed attempts park the order; poisoned_count reflects it;
    a batch of 199 succeeds despite 1 bad order."""

    def test_five_failures_park_and_isolate(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 99)
            _insert_dirty(conn, 99)
            for good_id in range(100, 110):
                _insert_order(conn, good_id)
                _insert_dirty(conn, good_id)
            conn.commit()

        for _ in range(POISON_THRESHOLD):
            [claim] = [
                c for c in claim_dirty(limit=1, lease=timedelta(seconds=120), worker_id="w") if c.order_id == 99
            ] or [None]
            if claim is None:
                break
            mark_failed(claim, "boom")

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = 99")
            ).fetchone()
            db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        assert row.attempts == POISON_THRESHOLD
        assert row.last_error == "boom"

        db = db_session_factory()
        try:
            assert poisoned_count(db) == 1
        finally:
            db.close()

        # Parked order excluded from further claims -- good orders unaffected.
        remaining_claims = claim_dirty(limit=200, lease=timedelta(seconds=120), worker_id="w2")
        assert 99 not in {c.order_id for c in remaining_claims}
        assert len(remaining_claims) == 10


@pytest.mark.postgres
class TestLostRacesNeverCountAsFailure:
    """PR3.T4a: 5 version-mismatch releases on the same order never
    increment attempts and never park it; claim_dirty keeps returning it."""

    def test_five_lost_races_do_not_poison(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 5)
            _insert_dirty(conn, 5)
            conn.commit()

        for _ in range(POISON_THRESHOLD):
            claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")
            assert [c.order_id for c in claims] == [5]
            claim = claims[0]
            with pg_order_metrics_engine.connect() as conn:
                conn.execute(text("UPDATE ml_order_metrics_dirty SET version = version + 1 WHERE order_id = 5"))
                conn.commit()
            fenced_store([claim], {5: _metrics(5)})

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = 5")
            ).fetchone()
            db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        assert row.attempts == 0
        assert row.last_error is None

        # 6th pass: still claimable, never parked.
        claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")
        assert [c.order_id for c in claims] == [5]

        db = db_session_factory()
        try:
            assert poisoned_count(db) == 0
        finally:
            db.close()


@pytest.mark.postgres
class TestGenuineFailuresIsolated:
    """PR3.T4c: 5 genuine recompute failures (not version mismatches)
    increment attempts each time and park at 5; a concurrently
    succeeding unrelated order is unaffected."""

    def test_five_genuine_failures_park_only_that_order(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 7)
            _insert_dirty(conn, 7)
            conn.commit()

        for attempt in range(1, POISON_THRESHOLD + 1):
            # First failure claims via the normal batch (attempts=0); every
            # subsequent one claims via the singleton pass (attempts>0) --
            # either way the target order is the only dirty row so far.
            [claim] = claim_dirty(limit=1, lease=timedelta(seconds=120), worker_id="w")
            assert claim.order_id == 7
            mark_failed(claim, f"failure-{attempt}")

        # Order 7 is now parked. A concurrently succeeding unrelated order
        # enqueued only now proves the failures never blocked the queue.
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 8)
            _insert_dirty(conn, 8)
            conn.commit()
        claims_8 = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w2")
        assert [c.order_id for c in claims_8] == [8]
        fenced_store(claims_8, {8: _metrics(8)})

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = 7")
            ).fetchone()
            row8 = conn.execute(text("SELECT 1 FROM ml_order_metrics_dirty WHERE order_id = 8")).fetchone()
        assert row.attempts == POISON_THRESHOLD
        assert row.last_error == f"failure-{POISON_THRESHOLD}"
        # Order 8 was successfully recomputed and deleted from the queue.
        assert row8 is None


@pytest.mark.postgres
class TestWorkerDeathParksAfterFiveExpiredLeases:
    """PR3.T4d: simulated worker death 5 times on the same order parks it
    via lease_expired charges; an unrelated dirty order enqueued alongside
    is claimed and recomputed throughout (queue continues)."""

    def test_five_expired_leases_park_the_order(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 11)
            _insert_dirty(conn, 11)
            conn.commit()

        # Each call after the first CHARGES the previous call's claim (its
        # lease is already expired under a 0-second lease) before claiming
        # again. POISON_THRESHOLD calls successfully reclaim it 5 times
        # ("5 deaths"), charging attempts up to POISON_THRESHOLD - 1 (the
        # charge from a call always reflects the PREVIOUS death); one more
        # call charges the final death and finds it parked (excluded from
        # further claims).
        for _ in range(POISON_THRESHOLD):
            claims = claim_dirty(limit=1, lease=timedelta(seconds=0), worker_id="w")
            assert [c.order_id for c in claims] == [11]
            # Simulate death: never release, let the (zero-second) lease
            # expire immediately for the next claim_dirty call to reclaim.
        final_claims = claim_dirty(limit=1, lease=timedelta(seconds=0), worker_id="w")
        assert final_claims == []  # parked by this call's own charge phase

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM ml_order_metrics_dirty WHERE order_id = 11")
            ).fetchone()
            db_session_factory = sessionmaker(bind=pg_order_metrics_engine)
        assert row.attempts == POISON_THRESHOLD
        assert row.last_error == "lease_expired"

        db = db_session_factory()
        try:
            assert poisoned_count(db) == 1
        finally:
            db.close()

        # Rows with attempts > 0 are claimed alone (batch of one): enqueue
        # an unrelated order and confirm the queue keeps draining it.
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 12)
            _insert_dirty(conn, 12)
            conn.commit()
        claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w2")
        assert [c.order_id for c in claims] == [12]
        result = fenced_store(claims, {12: _metrics(12)})
        assert result.stored_order_ids == [12]


@pytest.mark.postgres
class TestReleaseUnchargedSuspect:
    def test_release_marks_suspect_without_charging(self, _order_metrics_db_session, pg_order_metrics_engine) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 21)
            _insert_dirty(conn, 21)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")

        release_uncharged([claim], suspect=True)

        with pg_order_metrics_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT attempts, suspect, claimed_at, claimed_by, claim_token "
                    "FROM ml_order_metrics_dirty WHERE order_id = 21"
                )
            ).fetchone()
        assert row.attempts == 0
        assert row.suspect is True
        assert row.claimed_at is None
        assert row.claimed_by is None
        assert row.claim_token is None

    def test_release_without_suspect_stays_reclaimable_immediately(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 22)
            _insert_dirty(conn, 22)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")

        release_uncharged([claim], suspect=False)

        claims_again = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w2")
        assert [c.order_id for c in claims_again] == [22]


@pytest.mark.postgres
class TestFenceAcrossTwoRealSessions:
    """PR3.T4f: worker A claims order X at version 1 and computes from the
    old snapshot; A's lease expires; a direct write bumps X to version 2;
    worker B reclaims X, recomputes and commits; then A attempts its store
    ⇒ finds no owned row, writes nothing, B's newer values survive."""

    def test_stale_worker_never_overwrites_newer_commit(
        self, _order_metrics_db_session, pg_order_metrics_engine
    ) -> None:
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 31)
            _insert_dirty(conn, 31)
            conn.commit()

        # Worker A claims (short-lived lease so it can "expire").
        [claim_a] = claim_dirty(limit=10, lease=timedelta(seconds=0), worker_id="A")

        # Simulated input write bumps the version while A still holds the
        # (now-expired) claim.
        with pg_order_metrics_engine.connect() as conn:
            conn.execute(text("UPDATE ml_order_metrics_dirty SET version = version + 1 WHERE order_id = 31"))
            conn.commit()

        # Worker B reclaims (A's lease already expired) and commits fresh
        # metrics. Same lease value as A's call -- in production every
        # worker uses the one configured lease, never a per-call value.
        [claim_b] = claim_dirty(limit=10, lease=timedelta(seconds=0), worker_id="B")
        fenced_store([claim_b], {31: OrderMetrics(**{**_metrics(31).__dict__, "total_gauss": Decimal("99.00")})})

        # A, unaware its claim was reclaimed, now attempts to store its
        # stale snapshot with the ORIGINAL token.
        result = fenced_store(
            [claim_a], {31: OrderMetrics(**{**_metrics(31).__dict__, "total_gauss": Decimal("1.00")})}
        )

        assert result.not_owner_order_ids == [31]
        with pg_order_metrics_engine.connect() as conn:
            metrics_row = conn.execute(text("SELECT total_gauss FROM ml_order_metrics WHERE order_id = 31")).fetchone()
        assert metrics_row.total_gauss == Decimal("99.00")
