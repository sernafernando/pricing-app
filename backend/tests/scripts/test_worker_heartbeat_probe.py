"""`python -m app.scripts.worker_heartbeat <name>`: what the deploy reads to tell a live
worker from a hung one (`scripts/restart-verify-workers.sh`)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.scripts import worker_heartbeat


@pytest.fixture()
def session_factory(engine, monkeypatch):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", factory)
    yield factory
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))


def set_heartbeat(engine, name: str, value) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO worker_job_state (name, heartbeat_at) VALUES (:n, :h)"), {"n": name, "h": value})


class TestProbe:
    def test_prints_the_heartbeat_as_epoch_seconds(self, engine, session_factory, capsys) -> None:
        moment = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        set_heartbeat(engine, "worker-ml", moment)

        assert worker_heartbeat.main(["worker-ml"]) == 0

        assert float(capsys.readouterr().out.strip()) == pytest.approx(moment.timestamp())

    def test_a_worker_without_a_row_prints_none(self, engine, session_factory, capsys) -> None:
        assert worker_heartbeat.main(["worker-ml"]) == 0
        assert capsys.readouterr().out.strip() == "none"

    def test_a_row_without_a_heartbeat_prints_none(self, engine, session_factory, capsys) -> None:
        set_heartbeat(engine, "worker", None)

        worker_heartbeat.main(["worker"])

        assert capsys.readouterr().out.strip() == "none"

    def test_only_the_named_worker_is_read(self, engine, session_factory, capsys) -> None:
        set_heartbeat(engine, "worker", datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc))

        worker_heartbeat.main(["worker-ml"])

        assert capsys.readouterr().out.strip() == "none"

    def test_a_database_failure_exits_non_zero_and_prints_nothing_on_stdout(self, monkeypatch, capsys) -> None:
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("app.core.database.get_background_db", boom)

        assert worker_heartbeat.main(["worker"]) == 1

        captured = capsys.readouterr()
        assert captured.out == "" and "db down" in captured.err
