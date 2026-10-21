"""`backfill_sell_out_consumos` (T7 S2) against Postgres: rebuilds every campaign in
batches, a failing campaign alone, and a dry run in one rolled-back transaction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.scripts import backfill_sell_out_consumos as script
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_backfill") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


class _Sessions:
    """A session factory that counts the sessions and commits of the run."""

    def __init__(self, engine: Engine) -> None:
        self.factory = sessionmaker(bind=engine)
        self.sessions: List[Session] = []
        self.commits = 0

    def __call__(self) -> Session:
        db = self.factory()
        original = db.commit

        def commit() -> None:
            self.commits += 1
            original()

        db.commit = commit  # type: ignore[method-assign]
        self.sessions.append(db)
        return db


def _tres_campanas(engine: Engine) -> List[int]:
    grupo = w.grupo(engine, [ROUTERS])
    ids = [w.campana(engine, [grupo]) for _ in range(3)]
    w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
    return ids


def test_rebuilds_every_campaign_in_batches_and_a_rerun_writes_nothing(engine: Engine) -> None:
    ids = _tres_campanas(engine)
    sesiones = _Sessions(engine)

    summary = script.run_backfill(limit=None, dry_run=False, batch_size=2, session_factory=sesiones)

    assert [r[0] for r in w.consumos(engine)] == ids
    assert (summary["campanas"], summary["batches"], summary["inserted"], summary["deleted"]) == (3, 2, 3, 0)
    assert summary["last_campana_id"] == ids[-1] and summary["failed_campanas"] == []
    assert sesiones.commits == 2

    again = script.run_backfill(limit=None, dry_run=False, session_factory=sessionmaker(bind=engine))
    assert (again["inserted"], again["deleted"]) == (0, 0)


def test_a_dry_run_reports_in_one_transaction_and_writes_nothing(engine: Engine) -> None:
    _tres_campanas(engine)
    sesiones = _Sessions(engine)

    summary = script.run_backfill(limit=None, dry_run=True, batch_size=1, session_factory=sesiones)

    assert (summary["campanas"], summary["batches"], summary["inserted"]) == (3, 3, 3)
    assert (len(sesiones.sessions), sesiones.commits) == (1, 0)
    assert w.consumos(engine) == []


def test_a_failing_campaign_is_listed_and_the_others_are_written(engine: Engine) -> None:
    grupo = w.grupo(engine, [ROUTERS])
    mala = w.campana(engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="5")
    buena = w.campana(engine, [w.grupo(engine, [{"marca": "MERCUSYS"}])])
    w.venta(engine, "ml", 950, 1, D(2026, 11, 2))

    summary = script.run_backfill(limit=None, dry_run=False, session_factory=sessionmaker(bind=engine))

    assert summary["failed_campanas"] == [mala] and mala in summary["errors"]
    assert [(r[0], r[6]) for r in w.consumos(engine)] == [(buena, Decimal("10.00"))]


def test_a_database_error_in_one_campaign_does_not_poison_the_batch(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    rota = w.campana(engine, [w.grupo(engine, [ROUTERS])])
    sana = w.campana(engine, [w.grupo(engine, [{"marca": "MERCUSYS"}])])
    w.venta(engine, "ml", 950, 1, D(2026, 11, 2))
    real = script.recalcular

    def recalcular(db, ids):
        if list(ids) == [rota]:
            db.execute(text("SELECT 1 / 0"))  # aborts the transaction unless its savepoint is rolled back
        return real(db, ids)

    monkeypatch.setattr(script, "recalcular", recalcular)

    summary = script.run_backfill(limit=None, dry_run=False, session_factory=sessionmaker(bind=engine))

    assert summary["failed_campanas"] == [rota] and summary["stop_error"] is None
    assert [r[0] for r in w.consumos(engine)] == [sana]


def test_limit_after_and_an_explicit_list_bound_the_run(engine: Engine) -> None:
    ids = _tres_campanas(engine)
    factory = sessionmaker(bind=engine)

    primera = script.run_backfill(limit=1, dry_run=True, session_factory=factory)
    resto = script.run_backfill(limit=None, dry_run=True, after_campana=ids[0], session_factory=factory)
    solo = script.run_backfill(limit=None, dry_run=True, campanas=[ids[2], ids[2]], session_factory=factory)

    assert (primera["campanas"], primera["last_campana_id"]) == (1, ids[0])
    assert (resto["campanas"], resto["last_campana_id"]) == (2, ids[2])
    assert (solo["campanas"], solo["last_campana_id"]) == (1, ids[2])


def test_main_exits_1_when_a_campaign_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    def fake(**kwargs):
        calls.update(kwargs)
        return {"failed_campanas": [4], "stopped_at_after_campana": None}

    monkeypatch.setattr(script, "run_backfill", fake)

    assert script.main(["--dry-run", "--campanas", "4,2", "--batch-size", "5"]) == 1
    assert (calls["dry_run"], calls["campanas"], calls["batch_size"]) == (True, [2, 4], 5)


def test_invalid_bounds_are_refused() -> None:
    with pytest.raises(ValueError):
        script.run_backfill(limit=0, dry_run=True)
