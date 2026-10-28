"""Migration `20261207_sell_out_campana_items` (sell-in-sell-out T22b S25): the per-product amounts of a sell-out
campaign (legacy grouped offsets: each product its own amount under one shared cap), its downgrade, on a real
Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation, UniqueViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.models.sell_out import SellOutCampana
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261207_sell_out_campana_items"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "sell_out_campana_items"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",
]
_COLUMNS = (
    "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t ORDER BY ordinal_position"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_out_campana_items_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _campana(engine: Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, usuario_id) "
                "VALUES ('C', '2026-11-01', '2026-11-30', 'por_unidad', 10, 'ARS', 7) RETURNING id"
            )
        ).scalar_one()


def _item(engine: Engine, campana_id: int, item_id: int = 2964, monto="25.50") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_TABLE} (campana_id, item_id, monto_unit) VALUES (:c, :i, :m)"),
            {"c": campana_id, "i": item_id, "m": monto},
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_campana_items", [SellOutCampana.__table__], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_offsets_review_table_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261206_offsets_migracion_pendientes"
    # One head, with this revision on its line: later migrations stack on top of it.
    heads = script.get_heads()
    assert len(heads) == 1
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


@pytest.mark.postgres
def test_upgrade_creates_the_table_with_the_campaign_amount_type(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = [tuple(r) for r in conn.execute(text(_COLUMNS), {"t": _TABLE})]
    assert columns == [
        ("id", "bigint", 64, 0, "NO"),
        ("campana_id", "bigint", 64, 0, "NO"),
        ("item_id", "integer", 32, 0, "NO"),
        ("monto_unit", "numeric", 18, 2, "NO"),  # NUMERIC(18, 2), like sell_out_campanas.monto_unit
    ]
    _item(before, _campana(before))
    with before.connect() as conn:
        assert conn.execute(text(f"SELECT monto_unit FROM {_TABLE}")).scalar_one() == pytest.approx(25.5)


@pytest.mark.postgres
def test_one_amount_per_product_and_campaign(before) -> None:
    _step(before, "upgrade")
    campana = _campana(before)
    _item(before, campana)
    _item(before, campana, item_id=2270)
    _item(before, _campana(before))  # the same product in another campaign

    with pytest.raises(IntegrityError) as caught:
        _item(before, campana, monto="30")
    assert isinstance(caught.value.orig, UniqueViolation)


@pytest.mark.postgres
@pytest.mark.parametrize("monto", ["0", "-1"])
def test_the_amount_must_be_positive(before, monto) -> None:
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _item(before, _campana(before), monto=monto)
    assert isinstance(caught.value.orig, CheckViolation)


@pytest.mark.postgres
def test_deleting_the_campaign_deletes_its_amounts(before) -> None:
    _step(before, "upgrade")
    campana = _campana(before)
    _item(before, campana)
    with before.begin() as conn:
        conn.execute(text("DELETE FROM sell_out_campanas WHERE id = :c"), {"c": campana})
        assert conn.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one() == 0


@pytest.mark.postgres
def test_downgrade_drops_the_table_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text("SELECT to_regclass(:t)"), {"t": _TABLE}).scalar() is None
