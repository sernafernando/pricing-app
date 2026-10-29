"""Migration `20261215_sell_in_bono_acumulable` (sell-in-sell-out T27a, S36): every sell-in bonus carries an
`acumulable` flag, true by default and for every existing bonus, and a flag change queues the bonus; its downgrade, on
a real Postgres. `sell_in_bonos_marca` is a stub with the columns the update trigger reads, not the ORM."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261215_sell_in_bono_acumulable"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "sell_in_bonos_marca"
_STUBS = [
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT, marca TEXT, categoria TEXT, pedido_id BIGINT, tipo TEXT,
        monto_unit NUMERIC(18, 2), porcentaje NUMERIC(7, 4), moneda TEXT, fecha_desde DATE, fecha_hasta DATE,
        estado TEXT, usuario_id INTEGER, tope_unidades INTEGER, tope_monto NUMERIC(18, 2), base TEXT,
        incluye_iva BOOLEAN, descripcion TEXT
    )""",
    "INSERT INTO sell_in_bonos_marca (id, marca, base) VALUES (1, 'LENOVO', 'factura'), (2, 'EPSON', 'costo_venta')",
    "CREATE TABLE encolados (bono_id BIGINT)",
    # Stands in for the real queue function (20261115): records which bonus was queued.
    """CREATE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $$
    BEGIN INSERT INTO encolados VALUES (NEW.id); RETURN NULL; END $$ LANGUAGE plpgsql""",
]
_COLUMN = (
    "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t AND column_name = 'acumulable'"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_acumulable_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _update(engine: Engine, sql: str) -> list:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM encolados"))
        conn.execute(text(f"UPDATE {_TABLE} SET {sql} WHERE id = 1"))
        return [r[0] for r in conn.execute(text("SELECT bono_id FROM encolados"))]


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_acum", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_sell_out_fixed_total_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261214_sell_out_monto_total"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_adds_the_flag_true_by_default_and_every_existing_bonus_stacks(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        column = conn.execute(text(_COLUMN), {"t": _TABLE}).one()
        existentes = conn.execute(text(f"SELECT id, acumulable FROM {_TABLE} ORDER BY id")).all()
        conn.execute(text(f"INSERT INTO {_TABLE} (id, marca) VALUES (3, 'HP')"))
        nuevo = conn.execute(text(f"SELECT acumulable FROM {_TABLE} WHERE id = 3")).scalar()
    assert (column.data_type, column.is_nullable, column.column_default) == ("boolean", "NO", "true")
    assert [tuple(r) for r in existentes] == [(1, True), (2, True)]
    assert nuevo is True


@pytest.mark.postgres
def test_a_flag_change_queues_the_bonus_and_an_unrelated_change_does_not(before) -> None:
    _step(before, "upgrade")

    assert _update(before, "acumulable = false") == [1]
    assert _update(before, "acumulable = false") == []  # nothing changed
    assert _update(before, "acumulable = true") == [1]
    assert _update(before, "descripcion = 'otra'") == []
    # The fields queued before still queue.
    assert _update(before, "tope_monto = 3000") == [1]
    assert _update(before, "incluye_iva = true") == [1]
    assert _update(before, "marca = 'TP-LINK'") == [1]


@pytest.mark.postgres
def test_downgrade_drops_the_flag_restores_the_trigger_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _update(before, "acumulable = false")
    _update(before, "acumulable = true")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMN), {"t": _TABLE}).all() == []
    assert _update(before, "incluye_iva = true") == [1]
    assert _update(before, "descripcion = 'otra'") == []


@pytest.mark.postgres
def test_downgrade_refuses_while_a_bonus_is_not_acumulable_and_changes_nothing(before) -> None:
    _step(before, "upgrade")
    _update(before, "acumulable = false")

    with pytest.raises(Exception, match="not acumulable"):
        _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMN), {"t": _TABLE}).one().data_type == "boolean"
        assert conn.execute(text(f"SELECT acumulable FROM {_TABLE} WHERE id = 1")).scalar() is False
    assert _update(before, "acumulable = true") == [1]  # the trigger with the flag is still there


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"


def test_the_live_update_trigger_is_this_revisions() -> None:
    """`bono_queue.UPGRADE_SQL` (what the test worlds install) and this revision's bonus update trigger are the same."""
    from app.services.sell_in import bono_queue

    vivo = [s for s in bono_queue.UPGRADE_SQL if "CREATE TRIGGER trg_sell_in_bono_bonos_update" in s]
    assert len(vivo) == 1
    assert " ".join(vivo[0].split()) == " ".join(_module()._trigger(con_acumulable=True).split())
