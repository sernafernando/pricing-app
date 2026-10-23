"""Migration `20261115_sell_in_bono_queue_alcance` (sell-in-sell-out T3e-1, M2b): it
replaces the bonus queue's triggers with the scope-aware ones and its downgrade puts
back exactly what `20261107_sell_in_bonos_marca` installed. What the new triggers
queue is proven by tests/services/sell_in/test_bono_queue_postgres.py (they run
`bono_queue`'s SQL, which equals this migration's frozen copy)."""

from __future__ import annotations

import os
from typing import Dict, Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import LockNotAvailable
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from tests.models import test_sell_in_schema_postgres as base

_REVISION = "20261115_sell_in_bono_queue_alcance"
_PATH = next(p for p in base._MIGRATIONS if p.stem == _REVISION)
_BEFORE = [p for p in base._MIGRATIONS if p.stem != _REVISION]

_TRIGGERS = (
    "SELECT t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "WHERE c.relnamespace = current_schema()::regnamespace AND NOT t.tgisinternal AND t.tgname LIKE '%bono%'"
)
_FUNCTIONS = (
    "SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid) FROM pg_proc p "
    "WHERE p.pronamespace = current_schema()::regnamespace AND p.proname LIKE 'sell_in_bono%'"
)


def _snapshot(engine: Engine) -> Dict[str, Dict[str, str]]:
    with engine.connect() as conn:
        return {
            "triggers": dict(conn.execute(text(_TRIGGERS)).all()),
            "functions": dict(conn.execute(text(_FUNCTIONS)).all()),
        }


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(base._load_migration(_PATH), step)()


def _build(engine: Engine) -> None:
    for path in _BEFORE:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                base._load_migration(path).upgrade()


@pytest.fixture()
def before() -> Iterator[Engine]:
    with base._throwaway_schema("si_bono_queue_alc", _build) as engine:
        yield engine


def test_this_revision_chains_on_the_heads_merge_revision() -> None:
    config = Config(os.path.join(base._BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(base._BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261114_merge_ads_permiso_sell_in_bonos"
    assert len(script.get_heads()) == 1  # no divergent heads; a later revision may sit on top of this one


@pytest.mark.postgres
def test_upgrade_installs_the_scope_aware_gate_and_the_models_trigger(before):
    antes = _snapshot(before)

    _step(before, "upgrade")

    despues = _snapshot(before)
    assert set(despues["triggers"]) - set(antes["triggers"]) == {"trg_sell_in_bono_items_change"}
    assert "sell_in_bono_cubre_producto(date,bigint,integer,text,text)" in despues["functions"]
    assert "UPDATE OF marca, categoria ON" in despues["triggers"]["trg_sell_in_bono_productos_marca"]
    assert "importe_neto, moneda ON" in despues["triggers"]["trg_sell_in_bono_lineas_update"]
    assert "categoria" in despues["triggers"]["trg_sell_in_bono_bonos_update"]


@pytest.mark.postgres
def test_downgrade_puts_back_exactly_what_the_brand_bonus_migration_installed(before):
    antes = _snapshot(before)

    _step(before, "upgrade")
    _step(before, "downgrade")

    assert _snapshot(before) == antes
    _step(before, "upgrade")  # and it goes up again
    assert "trg_sell_in_bono_items_change" in _snapshot(before)["triggers"]


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as writer:
        tx = writer.begin()
        writer.exec_driver_sql("LOCK TABLE productos_erp IN ROW EXCLUSIVE MODE")
        try:
            with before.connect() as conn:
                conn.exec_driver_sql("SET statement_timeout = '20s'")  # bounds the test if it does block
                ctx = MigrationContext.configure(conn)
                with pytest.raises(OperationalError) as caught:
                    with ctx.begin_transaction(), Operations.context(ctx):
                        getattr(base._load_migration(_PATH), step)()
        finally:
            tx.rollback()
    assert isinstance(caught.value.orig, LockNotAvailable)


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(base._load_migration(_PATH), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"
