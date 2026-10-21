"""`app.scripts.reconcile_sell_in_bonos`: the idempotent full reconcile of every
brand bonus (initial backfill, run once after deploy; the `sell_in.bono` worker
keeps it current afterwards).

Postgres only (the reconcile takes advisory locks). Runs in a throwaway schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.scripts.reconcile_sell_in_bonos import main, run_reconcile
from tests.services.sell_in import _bono_world as b


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_script") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _run(engine: Engine, **kwargs) -> dict:
    return run_reconcile(session_factory=sessionmaker(bind=engine), **kwargs)


@pytest.mark.postgres
class TestReconcileScript:
    def test_it_applies_every_bonus_and_a_rerun_changes_nothing(self, engine: Engine) -> None:
        uno, otro = b.bono(engine, monto="1.00"), b.bono(engine, monto="2.00", estado="anulada")
        pedido = b.pedido(engine, {2964: 3})

        primera = _run(engine)
        segunda = _run(engine)

        assert [(g[0], g[1], g[4]) for g in b.generadas(engine)] == [(uno, pedido, Decimal("3.00"))]
        assert (primera["bonos"], primera["creadas"], primera["fallidas"]) == (2, 1, [])
        assert (segunda["creadas"], segunda["actualizadas"], segunda["anuladas"]) == (0, 0, 0)
        assert otro  # a voided bonus is reconciled too: it generates nothing

    def test_dry_run_reports_and_writes_nothing(self, engine: Engine) -> None:
        b.bono(engine)
        b.pedido(engine, {2964: 3})

        summary = _run(engine, dry_run=True)

        assert summary["creadas"] == 1
        assert b.generadas(engine) == []

    def test_dry_run_predicts_the_real_run_with_an_orphan_and_two_bonuses(self, engine: Engine) -> None:
        """Every reconcile call sweeps the orphans: the dry run must count one void, like the real run."""
        b.bono(engine, marca=b.TPLINK)
        b.bono(engine, marca=b.MERCUSYS)
        pedido = b.pedido(engine, {2964: 1})
        _run(engine)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": pedido})

        prevista = _run(engine, dry_run=True)
        real = _run(engine)

        assert (prevista["creadas"], prevista["actualizadas"], prevista["anuladas"]) == (0, 0, 1)
        assert (real["creadas"], real["actualizadas"], real["anuladas"]) == (0, 0, 1)

    def test_failed_pairs_are_listed_and_the_exit_code_is_one(self, engine: Engine, monkeypatch) -> None:
        bono = b.bono(engine, moneda="USD")
        pedido = b.pedido(engine, {2964: 1}, moneda="ARS", tipo_cambio=None)
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))

        summary = _run(engine)

        assert [f[:2] for f in summary["fallidas"]] == [[bono, pedido]]
        assert main([]) == 1
