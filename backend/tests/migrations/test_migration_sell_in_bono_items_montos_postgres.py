"""Migration `20261210_sell_in_bono_items_montos` (sell-in-sell-out T23a): a model of a 'modelos' bonus may carry
its own `monto_unit` or `porcentaje` (legacy grouped offsets: each product its own amount), its downgrade, on a
real Postgres. `sell_in_bono_items` is created with its production DDL (20261114), not from the ORM."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator, Optional

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
_REVISION = "20261210_sell_in_bono_items_montos"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "sell_in_bono_items"
_STUBS = [
    "CREATE TABLE sell_in_bonos_marca (id BIGSERIAL PRIMARY KEY)",
    "INSERT INTO sell_in_bonos_marca (id) VALUES (1)",
    """CREATE TABLE sell_in_bono_items (
        id BIGSERIAL PRIMARY KEY,
        bono_id BIGINT NOT NULL REFERENCES sell_in_bonos_marca (id) ON DELETE CASCADE,
        item_id INTEGER NOT NULL,
        CONSTRAINT uq_sell_in_bono_items_bono_item UNIQUE (bono_id, item_id)
    )""",
    "INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (1, 2964)",
]
_COLUMNS = (
    "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t AND column_name IN ('monto_unit', 'porcentaje') "
    "ORDER BY column_name"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_items_montos_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _item(engine: Engine, item_id: int, monto: Optional[str] = None, porcentaje: Optional[str] = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_TABLE} (bono_id, item_id, monto_unit, porcentaje) VALUES (1, :i, :m, :p)"),
            {"i": item_id, "m": monto, "p": porcentaje},
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_items_montos", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_sell_out_campaign_items_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261207_sell_out_campana_items"
    assert len(script.get_heads()) == 1  # no divergent heads; a later revision may sit on top of this one


@pytest.mark.postgres
def test_upgrade_adds_both_values_nullable_with_the_bonus_types(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = [tuple(r) for r in conn.execute(text(_COLUMNS), {"t": _TABLE})]
        existente = conn.execute(text(f"SELECT monto_unit, porcentaje FROM {_TABLE} WHERE item_id = 2964")).one()
    # NUMERIC(18, 2) and NUMERIC(7, 4), like sell_in_bonos_marca.monto_unit / .porcentaje.
    assert columns == [("monto_unit", "numeric", 18, 2, "YES"), ("porcentaje", "numeric", 7, 4, "YES")]
    assert tuple(existente) == (None, None)  # a model already listed keeps the bonus value
    _item(before, 2270, monto="3.50")
    _item(before, 950, porcentaje="100")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "monto,porcentaje",
    [("0", None), ("-1", None), (None, "0"), (None, "-2"), (None, "100.01"), ("1.00", "2")],
    ids=["monto-cero", "monto-negativo", "pct-cero", "pct-negativo", "pct-sobre-100", "los-dos"],
)
def test_a_value_must_be_positive_in_range_and_only_one_of_them(before, monto, porcentaje) -> None:
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _item(before, 2270, monto=monto, porcentaje=porcentaje)
    assert isinstance(caught.value.orig, CheckViolation)


@pytest.mark.postgres
def test_downgrade_drops_both_columns_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _item(before, 2270, monto="3.50")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNS), {"t": _TABLE}).all() == []
        assert conn.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one() == 2


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
