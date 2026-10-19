"""`promo_write.refresh`: drains `promo_refresh_pending` (the ~60 s follow-up refresh a promo write queues)
from the ML worker, dropping stale backlog instead of replaying it. No cron.

Postgres only (the claim uses `FOR UPDATE SKIP LOCKED`). The ml-webhook client is the only thing mocked.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_background_db
from app.models.promo_refresh_pending import PromoRefreshPending
from app.services import promo_refresh_drain as drain
from app.services.ml_webhook_client import RefreshOutcome, ml_webhook_client
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers.promo_refresh import promo_write_refresh as handler
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

pytestmark = pytest.mark.postgres

_TABLES = [PromoRefreshPending.__table__]
# Per test engine -> an engine with its own, unpooled connections. Assertions read through it, never through a
# connection the drain may have used, so an effect only shows up if the drain's session committed it.
_READERS: dict[Engine, Engine] = {}


def now() -> datetime:
    return datetime.now(UTC)


def ctx(seconds: float = 30) -> WorkerContext:
    return WorkerContext(deadline=now() + timedelta(seconds=seconds), worker_name="test")


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    schema = f"promo_refresh_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                table.create(bind=conn)
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
        monkeypatch.setattr(settings, "PROMOS_WRITE_ENABLED", True)
        _READERS[engine] = create_engine(
            POSTGRES_TEST_URL, poolclass=NullPool, connect_args={"options": f"-csearch_path={schema}"}
        )
        yield engine
    finally:
        reader = _READERS.pop(engine, None)
        if reader is not None:
            reader.dispose()
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture()
def proxy() -> Iterator[mock.AsyncMock]:
    with mock.patch.object(
        ml_webhook_client, "refresh_item_promotions", new=mock.AsyncMock(return_value=RefreshOutcome(ok=True))
    ) as call:
        yield call


def put(engine: Engine, mla: str, *, due_in: float = -1, attempts: int = 0) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO promo_refresh_pending (mla, due_at, attempts) VALUES (:m, :d, :a)"),
            {"m": mla, "d": now() + timedelta(seconds=due_in), "a": attempts},
        )


def rows(engine: Engine) -> dict:
    """The table as a FRESH connection sees it (committed state only)."""
    with _READERS[engine].connect() as conn:
        return {r.mla: r for r in conn.execute(text("SELECT mla, due_at, attempts FROM promo_refresh_pending"))}


def called(proxy: mock.AsyncMock) -> list[str]:
    return [c.args[0] for c in proxy.await_args_list]


class TestRegistration:
    def test_it_runs_every_30_seconds_in_the_ml_worker_and_not_in_the_sales_one(self) -> None:
        assert handler in registry.ML_PUBLICATIONS_REGISTRY
        assert handler not in registry.REGISTRY
        assert handler.name == "promo_write.refresh"
        assert handler.channels == ()
        assert handler.interval == timedelta(seconds=30)
        assert handler.run_at_local is None


class TestDrain:
    def test_a_due_row_is_refreshed_once_and_removed(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")

        result = handler.run(ctx())

        assert result.success is True
        assert called(proxy) == ["MLA1"]
        assert rows(pg_engine) == {}
        assert result.detail["refreshed"] == 1

    def test_a_row_not_yet_due_is_untouched(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1", due_in=60)
        before = rows(pg_engine)["MLA1"]

        result = handler.run(ctx())

        assert called(proxy) == []
        assert rows(pg_engine)["MLA1"] == before
        assert result.detail["refreshed"] == 0

    def test_no_session_is_held_while_the_proxy_is_called(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")
        seen: list[int] = []

        async def refresh(mla: str) -> RefreshOutcome:
            seen.append(pg_engine.pool.checkedout())
            return RefreshOutcome(ok=True)

        proxy.side_effect = refresh

        handler.run(ctx())

        assert seen == [0]

    def test_a_write_that_requeues_the_mla_during_the_call_survives_it(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")

        async def refresh(mla: str) -> RefreshOutcome:
            with pg_engine.begin() as conn:  # what `_enqueue_refresh_retry` does on a new write
                conn.execute(
                    text("UPDATE promo_refresh_pending SET due_at = :d, attempts = 0 WHERE mla = :m"),
                    {"d": now() + timedelta(seconds=60), "m": mla},
                )
            return RefreshOutcome(ok=True)

        proxy.side_effect = refresh

        result = handler.run(ctx())

        assert rows(pg_engine)["MLA1"].attempts == 0
        assert rows(pg_engine)["MLA1"].due_at > now()
        assert result.detail["refreshed"] == 0
        assert result.detail["superseded"] == 1

    def test_a_non_retryable_drop_after_a_requeue_during_the_call_is_not_counted(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")

        async def refresh(mla: str) -> RefreshOutcome:
            with pg_engine.begin() as conn:
                conn.execute(
                    text("UPDATE promo_refresh_pending SET due_at = :d, attempts = 0 WHERE mla = :m"),
                    {"d": now() + timedelta(seconds=60), "m": mla},
                )
            return RefreshOutcome(ok=False, motivo="cerrada", reintentable=False)

        proxy.side_effect = refresh

        result = handler.run(ctx())

        assert set(rows(pg_engine)) == {"MLA1"}
        assert result.detail["dropped"] == 0
        assert result.detail["superseded"] == 1

    def test_the_batch_is_bounded_and_takes_the_oldest_due_first(self, pg_engine, proxy, monkeypatch) -> None:
        monkeypatch.setattr(drain, "MAX_ROWS_PER_RUN", 2)
        put(pg_engine, "MLA_NEWEST", due_in=-10)
        put(pg_engine, "MLA_OLDEST", due_in=-300)
        put(pg_engine, "MLA_MIDDLE", due_in=-100)

        result = handler.run(ctx())

        assert called(proxy) == ["MLA_OLDEST", "MLA_MIDDLE"]
        assert set(rows(pg_engine)) == {"MLA_NEWEST"}
        assert result.detail["refreshed"] == 2
        assert result.detail["capped"] is True

    def test_a_passed_deadline_starts_no_call(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")

        result = handler.run(ctx(seconds=-1))

        assert called(proxy) == []
        assert set(rows(pg_engine)) == {"MLA1"}
        assert result.detail["stopped"] == "deadline"

    def test_the_kill_switch_reads_and_calls_nothing(self, pg_engine, proxy, monkeypatch) -> None:
        monkeypatch.setattr(settings, "PROMOS_WRITE_ENABLED", False)
        put(pg_engine, "MLA1")
        put(pg_engine, "MLA_STALE", due_in=-3 * 86400)

        result = handler.run(ctx())

        assert result.success is True
        assert result.detail == {"skipped": "PROMOS_WRITE_ENABLED is off"}
        assert called(proxy) == []
        assert set(rows(pg_engine)) == {"MLA1", "MLA_STALE"}


class TestStaleBacklog:
    def test_stale_rows_are_dropped_without_a_refresh_call(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA_STALE_1", due_in=-3 * 86400)
        put(pg_engine, "MLA_STALE_2", due_in=-25 * 3600)
        put(pg_engine, "MLA_FRESH", due_in=-23 * 3600)

        result = handler.run(ctx())

        assert called(proxy) == ["MLA_FRESH"]
        assert rows(pg_engine) == {}
        assert result.detail["stale_dropped"] == 2
        assert result.detail["refreshed"] == 1

    def test_the_stale_purge_is_bounded_per_run(self, pg_engine, proxy, monkeypatch) -> None:
        monkeypatch.setattr(drain, "STALE_PURGE_BATCH", 2)
        for i in range(3):
            put(pg_engine, f"MLA_STALE_{i}", due_in=-2 * 86400 - i)

        result = handler.run(ctx())

        assert result.detail["stale_dropped"] == 2
        assert len(rows(pg_engine)) == 1
        assert called(proxy) == []


class TestFailures:
    def test_a_retryable_failure_charges_an_attempt_and_backs_off_60_seconds(self, pg_engine, proxy, caplog) -> None:
        put(pg_engine, "MLA1")
        proxy.return_value = RefreshOutcome(ok=False, motivo="proxy 502", reintentable=True)
        before = now()

        with caplog.at_level(logging.WARNING):
            result = handler.run(ctx())

        row = rows(pg_engine)["MLA1"]
        assert row.attempts == 1
        assert before + timedelta(seconds=59) <= row.due_at <= now() + timedelta(seconds=61)
        assert result.detail["failed"] == 1
        assert "MLA1" in caplog.text and "proxy 502" in caplog.text

    def test_an_exception_from_the_client_is_a_retryable_failure(self, pg_engine, proxy, caplog) -> None:
        put(pg_engine, "MLA1")
        proxy.side_effect = RuntimeError("boom")

        with caplog.at_level(logging.WARNING):
            result = handler.run(ctx())

        assert result.success is True
        assert rows(pg_engine)["MLA1"].attempts == 1
        assert result.detail["failed"] == 1
        assert "refresh_item_promotions raised for MLA1" in caplog.text

    def test_a_non_retryable_failure_drops_the_row_without_charging(self, pg_engine, proxy, caplog) -> None:
        put(pg_engine, "MLA1")
        proxy.return_value = RefreshOutcome(ok=False, motivo="publicacion cerrada", reintentable=False)

        with caplog.at_level(logging.WARNING):
            result = handler.run(ctx())

        assert rows(pg_engine) == {}
        assert result.detail["dropped"] == 1
        assert result.detail["failed"] == 0
        assert "MLA1 dropped, not retryable: publicacion cerrada" in caplog.text

    def test_the_fifth_failure_quarantines_the_row(self, pg_engine, proxy, caplog) -> None:
        put(pg_engine, "MLA1", attempts=drain.MAX_ATTEMPTS - 1)
        proxy.return_value = RefreshOutcome(ok=False, motivo="timeout", reintentable=True)

        with caplog.at_level(logging.ERROR):
            result = handler.run(ctx())

        assert rows(pg_engine) == {}
        assert result.detail["quarantined"] == 1
        assert "MLA1 QUARANTINED after 5 attempts" in caplog.text

    def test_one_failing_mla_does_not_stop_the_others(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA_BAD", due_in=-20)
        put(pg_engine, "MLA_GOOD", due_in=-10)

        async def refresh(mla: str) -> RefreshOutcome:
            if mla == "MLA_BAD":
                raise RuntimeError("boom")
            return RefreshOutcome(ok=True)

        proxy.side_effect = refresh

        result = handler.run(ctx())

        assert called(proxy) == ["MLA_BAD", "MLA_GOOD"]
        assert set(rows(pg_engine)) == {"MLA_BAD"}
        assert result.detail["refreshed"] == 1
        assert result.detail["failed"] == 1


class TestCommittedEffects:
    """Every effect is read from a fresh connection: a session that stopped committing would fail these."""

    def test_a_claim_commits_the_lease_and_the_attempt_charge(self, pg_engine) -> None:
        put(pg_engine, "MLA1", attempts=1)

        with get_background_db() as db:
            claim, quarantined = drain.claim_one(db, now())

        row = rows(pg_engine)["MLA1"]
        assert claim is not None and quarantined == 0
        assert row.attempts == 2
        assert row.due_at == claim.leased_until
        assert row.due_at > now() + timedelta(seconds=drain.CLAIM_LEASE_SECONDS - 5)

    def test_the_stale_purge_is_committed(self, pg_engine) -> None:
        put(pg_engine, "MLA_STALE", due_in=-2 * 86400)

        with get_background_db() as db:
            assert drain.purge_stale(db, now()) == 1

        assert rows(pg_engine) == {}

    def test_the_delete_after_a_success_is_committed(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1")

        handler.run(ctx())

        assert rows(pg_engine) == {}


class TestLeaseRecovery:
    def test_an_expired_lease_out_of_attempts_is_quarantined_at_claim_without_a_call(
        self, pg_engine, proxy, caplog
    ) -> None:
        put(pg_engine, "MLA_DEAD", due_in=-1, attempts=drain.MAX_ATTEMPTS)

        with caplog.at_level(logging.ERROR):
            result = handler.run(ctx())

        assert called(proxy) == []
        assert rows(pg_engine) == {}
        assert result.detail["quarantined"] == 1
        assert "MLA_DEAD QUARANTINED after 5 attempts" in caplog.text

    def test_an_expired_lease_under_the_cap_is_claimed_again(self, pg_engine, proxy) -> None:
        put(pg_engine, "MLA1", due_in=-1, attempts=2)
        proxy.return_value = RefreshOutcome(ok=False, motivo="proxy 502")

        result = handler.run(ctx())

        assert called(proxy) == ["MLA1"]
        assert rows(pg_engine)["MLA1"].attempts == 3
        assert result.detail["failed"] == 1


class TestDatabaseErrors:
    """A DB error on one row is logged and counted; the pass goes on and the handler does not raise."""

    def test_a_settle_error_on_one_row_does_not_stop_the_others(self, pg_engine, proxy, monkeypatch, caplog) -> None:
        put(pg_engine, "MLA_BAD", due_in=-20)
        put(pg_engine, "MLA_GOOD", due_in=-10)
        real_settle = drain._settle

        def settle(db, claim, outcome, detail):
            if claim.mla == "MLA_BAD":
                raise OperationalError("UPDATE promo_refresh_pending", {}, Exception("connection reset"))
            return real_settle(db, claim, outcome, detail)

        monkeypatch.setattr(drain, "_settle", settle)

        with caplog.at_level(logging.ERROR):
            result = handler.run(ctx())

        assert result.success is True
        assert called(proxy) == ["MLA_BAD", "MLA_GOOD"]
        assert result.detail["errors"] == 1
        assert result.detail["refreshed"] == 1
        bad = rows(pg_engine)["MLA_BAD"]
        assert bad.attempts == 1 and bad.due_at > now()  # still leased: it recovers when the lease expires
        assert "MLA_GOOD" not in rows(pg_engine)
        assert "settling MLA_BAD failed" in caplog.text

    def test_a_claim_error_does_not_stop_the_pass(self, pg_engine, proxy, monkeypatch, caplog) -> None:
        put(pg_engine, "MLA1")
        real_claim = drain.claim_one
        calls = {"n": 0}

        def claim_one(db, at):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("SELECT promo_refresh_pending", {}, Exception("lock timeout"))
            return real_claim(db, at)

        monkeypatch.setattr(drain, "claim_one", claim_one)

        with caplog.at_level(logging.ERROR):
            result = handler.run(ctx())

        assert result.success is True
        assert called(proxy) == ["MLA1"]
        assert result.detail["errors"] == 1
        assert result.detail["refreshed"] == 1
        assert "claiming a row failed" in caplog.text
