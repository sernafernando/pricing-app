"""Migration `20261106_combo_consumos_item` (combos in sell in / sell out): a combo sale counts for each component, so
two components of one sale may sit in the same campaign or cost bonus. The unique keys of `sell_out_consumos` and
`sell_in_bono_consumos` widen to include `item_id`; no data changes. Upgrade and downgrade on a real Postgres, over
stubs with the columns the keys use."""

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
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261106_combo_consumos_item"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    """CREATE TABLE sell_out_consumos (
        id BIGSERIAL PRIMARY KEY, campana_id BIGINT NOT NULL, canal TEXT NOT NULL, venta_ref BIGINT NOT NULL,
        item_id INTEGER NOT NULL,
        CONSTRAINT uq_sell_out_consumos_campana_canal_venta UNIQUE (campana_id, canal, venta_ref)
    )""",
    """CREATE TABLE sell_in_bono_consumos (
        id BIGSERIAL PRIMARY KEY, bono_id BIGINT NOT NULL, canal TEXT NOT NULL, venta_ref BIGINT NOT NULL,
        item_id INTEGER NOT NULL,
        CONSTRAINT uq_sell_in_bono_consumos_bono_canal_venta UNIQUE (bono_id, canal, venta_ref)
    )""",
    "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id) VALUES (1, 'fuera', 10, 950)",
    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id) VALUES (1, 'fuera', 10, 950)",
]
_TABLAS = {"sell_out_consumos": "campana_id", "sell_in_bono_consumos": "bono_id"}


def _module():
    spec = importlib.util.spec_from_file_location("combo_consumos_item_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _otro_componente(engine: Engine, tabla: str) -> None:
    """The same sale and campaign/bonus, another product: a combo's second component."""
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {tabla} ({_TABLAS[tabla]}, canal, venta_ref, item_id) VALUES (1, 'fuera', 10, 2964)")
        )


def _filas(engine: Engine, tabla: str) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(f"SELECT canal, venta_ref, item_id FROM {tabla} ORDER BY id"))]


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("combo_consumos_item", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_manual_cost_mode_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261106_sell_in_modo_manual"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("tabla", sorted(_TABLAS))
def test_upgrade_lets_two_components_of_one_sale_share_a_campaign_and_keeps_the_rows(before, tabla) -> None:
    with pytest.raises(IntegrityError):
        _otro_componente(before, tabla)

    _step(before, "upgrade")
    _otro_componente(before, tabla)

    assert _filas(before, tabla) == [("fuera", 10, 950), ("fuera", 10, 2964)]
    with pytest.raises(IntegrityError):  # the same product twice is still refused
        with before.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {tabla} ({_TABLAS[tabla]}, canal, venta_ref, item_id) VALUES (1, 'fuera', 10, 950)")
            )


@pytest.mark.postgres
@pytest.mark.parametrize("tabla", sorted(_TABLAS))
def test_downgrade_restores_the_narrow_key(before, tabla) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")

    with pytest.raises(IntegrityError):
        _otro_componente(before, tabla)
    assert _filas(before, tabla) == [("fuera", 10, 950)]


@pytest.mark.postgres
@pytest.mark.parametrize("tabla", sorted(_TABLAS))
def test_downgrade_keeps_one_row_per_sale_the_oldest(before, tabla) -> None:
    _step(before, "upgrade")
    _otro_componente(before, tabla)

    _step(before, "downgrade")

    assert _filas(before, tabla) == [("fuera", 10, 950)]
