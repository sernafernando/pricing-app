"""Migration `20261112_sell_in_compras_porcentaje` (sell-in-sell-out T3g-2): a purchase
is either a fixed amount (`tipo = 'monto'`, every existing row) or a percentage of
the invoiced net (`tipo = 'porcentaje'` with `porcentaje` in (0, 100]). Inert: no
reader yet. Upgrade, downgrade and lock handling on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation, LockNotAvailable
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261112_sell_in_compras_porcentaje"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
# Stand-in for `sell_in_compras` as it is before this revision (only what it touches).
_STUBS = ["CREATE TABLE sell_in_compras (id BIGSERIAL PRIMARY KEY, monto_total NUMERIC(18, 2) NOT NULL)"]
_COLUMNS = (
    "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale, column_default "
    "FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_in_compras' AND column_name IN ('tipo', 'porcentaje') ORDER BY column_name"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_compras_porcentaje_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _insert(engine: Engine, tipo, porcentaje) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sell_in_compras (monto_total, tipo, porcentaje) VALUES (10, :t, :p)"),
            {"t": tipo, "p": porcentaje},
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_porcentaje", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_offset_origin_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261111_sell_out_offset_origen"
    assert len(script.get_heads()) == 1  # no divergent heads; a later revision may sit on top of this one


@pytest.mark.postgres
def test_upgrade_adds_tipo_defaulting_to_monto_and_a_nullable_porcentaje(before):
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = conn.execute(text(_COLUMNS)).all()
    assert [(c[0], c[1], c[2], c[3], c[4]) for c in columns] == [
        ("porcentaje", "numeric", "YES", 7, 4),
        ("tipo", "character varying", "NO", None, None),
    ]
    assert columns[1][5].startswith("'monto'")


@pytest.mark.postgres
def test_upgrade_turns_every_existing_purchase_into_a_fixed_amount(before):
    with before.begin() as conn:
        conn.execute(text("INSERT INTO sell_in_compras (monto_total) VALUES (1), (2)"))
    _step(before, "upgrade")
    with before.connect() as conn:
        rows = conn.execute(text("SELECT monto_total, tipo, porcentaje FROM sell_in_compras ORDER BY id")).all()
    assert [(int(m), t, p) for m, t, p in rows] == [(1, "monto", None), (2, "monto", None)]


@pytest.mark.postgres
@pytest.mark.parametrize(("tipo", "porcentaje"), [("monto", None), ("porcentaje", "0.0001"), ("porcentaje", "100")])
def test_upgrade_accepts_a_fixed_amount_or_a_percentage_up_to_100(before, tipo, porcentaje):
    _step(before, "upgrade")
    _insert(before, tipo, porcentaje)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("tipo", "porcentaje"),
    [
        ("monto", "2"),  # a fixed amount carries no percentage
        ("porcentaje", None),  # a percentage purchase needs its percentage
        ("porcentaje", "0"),
        ("porcentaje", "-1"),
        ("porcentaje", "100.0001"),
        ("bono", None),  # unknown tipo
    ],
)
def test_upgrade_refuses_a_tipo_and_percentage_that_do_not_match(before, tipo, porcentaje):
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _insert(before, tipo, porcentaje)
    assert isinstance(caught.value.orig, CheckViolation)


@pytest.mark.postgres
def test_downgrade_drops_both_columns_and_is_idempotent(before):
    _step(before, "upgrade")
    _insert(before, "porcentaje", "2")

    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNS)).all() == []
        assert conn.execute(text("SELECT COUNT(*) FROM sell_in_compras")).scalar() == 1


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as writer:
        tx = writer.begin()
        writer.exec_driver_sql("LOCK TABLE sell_in_compras IN ROW EXCLUSIVE MODE")
        try:
            with before.connect() as conn:
                conn.exec_driver_sql("SET statement_timeout = '20s'")  # bounds the test if it does block
                ctx = MigrationContext.configure(conn)
                with pytest.raises(OperationalError) as caught:
                    with ctx.begin_transaction(), Operations.context(ctx):
                        getattr(_module(), step)()
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
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"
