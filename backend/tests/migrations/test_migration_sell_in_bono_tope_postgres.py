"""Migration `20261211_sell_in_bono_tope` (sell-in-sell-out T24a): a sell-in bonus may carry one cap shared by every
product it reaches, in units and/or money, and a cap change queues the bonus; its downgrade, on a real Postgres.
`sell_in_bonos_marca` is a stub with the columns the update trigger reads, not the ORM."""

from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261211_sell_in_bono_tope"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "sell_in_bonos_marca"
_STUBS = [
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT, marca TEXT, categoria TEXT, pedido_id BIGINT, tipo TEXT,
        monto_unit NUMERIC(18, 2), porcentaje NUMERIC(7, 4), moneda TEXT, fecha_desde DATE, fecha_hasta DATE,
        estado TEXT, usuario_id INTEGER, descripcion TEXT
    )""",
    "INSERT INTO sell_in_bonos_marca (id, marca) VALUES (1, 'LENOVO')",
    "CREATE TABLE encolados (bono_id BIGINT)",
    # Stands in for the real queue function (20261115): records which bonus was queued.
    """CREATE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $$
    BEGIN INSERT INTO encolados VALUES (NEW.id); RETURN NULL; END $$ LANGUAGE plpgsql""",
]
_COLUMNS = (
    "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t AND column_name IN ('tope_unidades', 'tope_monto') "
    "ORDER BY column_name"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_tope_migration", _PATH)
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
    with throwaway_schema("si_bono_tope", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_per_model_values_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261210_sell_in_bono_items_montos"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_adds_both_caps_nullable_and_existing_bonuses_have_none(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = [tuple(r) for r in conn.execute(text(_COLUMNS), {"t": _TABLE})]
        existente = conn.execute(text(f"SELECT tope_unidades, tope_monto FROM {_TABLE} WHERE id = 1")).one()
    assert columns == [("tope_monto", "numeric", 18, 2, "YES"), ("tope_unidades", "integer", 32, 0, "YES")]
    assert tuple(existente) == (None, None)
    assert _update(before, "tope_unidades = 500, tope_monto = 3000.00") == [1]
    with before.connect() as conn:
        guardado = conn.execute(text(f"SELECT tope_unidades, tope_monto FROM {_TABLE} WHERE id = 1")).one()
    assert tuple(guardado) == (500, Decimal("3000.00"))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "sql",
    ["tope_unidades = 0", "tope_unidades = -1", "tope_monto = 0", "tope_monto = -0.01"],
    ids=["unidades-cero", "unidades-negativo", "monto-cero", "monto-negativo"],
)
def test_a_cap_must_be_positive(before, sql) -> None:
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _update(before, sql)
    assert isinstance(caught.value.orig, CheckViolation)


@pytest.mark.postgres
def test_a_cap_change_queues_the_bonus_and_an_unrelated_change_does_not(before) -> None:
    _step(before, "upgrade")

    assert _update(before, "tope_monto = 3000") == [1]
    assert _update(before, "tope_unidades = 10") == [1]
    assert _update(before, "tope_monto = NULL") == [1]
    assert _update(before, "tope_monto = NULL") == []  # nothing changed
    assert _update(before, "descripcion = 'otra'") == []
    assert _update(before, "marca = 'TP-LINK'") == [1]  # the fields queued before still queue


@pytest.mark.postgres
def test_downgrade_drops_both_caps_restores_the_trigger_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _update(before, "tope_monto = 3000")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNS), {"t": _TABLE}).all() == []
    assert _update(before, "marca = 'TP-LINK'") == [1]
    assert _update(before, "descripcion = 'otra'") == []


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
