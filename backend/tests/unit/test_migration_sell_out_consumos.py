"""Migration `20261108_sell_out_consumos`: the allocation rows, the recompute
queue and the campaign VAT flag (T7 S1).

The parity with the ORM is proven by `tests/models/test_sell_out_schema_postgres.py`
(which runs this migration after `20261105_sell_out_campanas`); this module proves
the chain, the database rules the allocator will rely on and the downgrade.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.models import test_sell_out_schema_postgres as base

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "20261108_sell_out_consumos"
_INSERT_CONSUMO = (
    "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto, tc_venta) "
    "VALUES (:c, :canal, :ref, 1, DATE '2026-11-03', :u, :monto, :tc)"
)


def _consumo(campana_id: int, **overrides) -> dict:
    row = {"c": campana_id, "canal": "ml", "ref": 500, "u": 2, "monto": "20.00", "tc": None}
    row.update(overrides)
    return row


def _scripts() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _step(engine: Engine, path: Path, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(base._load_migration(path), step)()


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with base._throwaway_schema("so_consumos_mig", lambda eng: base._run(eng, "upgrade")) as eng:
        yield eng


def _names(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(sql))}


_TABLES = "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
_CAMPANA_COLUMNS = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_out_campanas'"
)


class TestMigrationGraph:
    def test_this_revision_chains_on_the_previous_one(self) -> None:
        # Not `get_heads() == [this]`: a later revision must not break this test.
        revision = _scripts().get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == "20261107_sell_in_bonos_marca"


@pytest.mark.postgres
class TestSellOutConsumosMigration:
    def test_existing_campaigns_get_the_vat_flag_off(self) -> None:
        with base._throwaway_schema("so_consumos_iva", lambda eng: _step(eng, base._MIGRATIONS[0], "upgrade")) as eng:
            with eng.begin() as conn:
                campana_id = base._new(conn)
            _step(eng, base._MIGRATIONS[1], "upgrade")
            with eng.begin() as conn:
                flag = conn.execute(
                    text("SELECT monto_incluye_iva FROM sell_out_campanas WHERE id = :i"), {"i": campana_id}
                ).scalar_one()
                nueva = base._new(conn)
                flag_nueva = conn.execute(
                    text("SELECT monto_incluye_iva FROM sell_out_campanas WHERE id = :i"), {"i": nueva}
                ).scalar_one()
        assert (flag, flag_nueva) == (False, False)

    def test_the_vat_flag_is_not_nullable(self, engine: Engine) -> None:
        with engine.begin() as conn:
            campana_id = base._new(conn)
        base._rejects(engine, "UPDATE sell_out_campanas SET monto_incluye_iva = NULL WHERE id = :i", {"i": campana_id})

    @pytest.mark.parametrize(
        "overrides",
        [
            {"canal": "amazon"},
            {"u": 0},
            {"u": -1},
            {"monto": "-0.01"},
            {"tc": "0"},
        ],
    )
    def test_row_checks(self, engine: Engine, overrides) -> None:
        with engine.begin() as conn:
            campana_id = base._new(conn)
        base._rejects(engine, _INSERT_CONSUMO, _consumo(campana_id, **overrides))

    def test_one_row_per_campaign_and_sale(self, engine: Engine) -> None:
        with engine.begin() as conn:
            campana_id, otra = base._new(conn), base._new(conn)
            conn.execute(text(_INSERT_CONSUMO), _consumo(campana_id, monto="0", tc="1450.5"))
            conn.execute(text(_INSERT_CONSUMO), _consumo(campana_id, canal="fuera"))  # another channel's keyspace
            conn.execute(text(_INSERT_CONSUMO), _consumo(otra))  # the same sale in another campaign
        base._rejects(engine, _INSERT_CONSUMO, _consumo(campana_id))

    def test_a_sale_reference_has_no_foreign_key(self, engine: Engine) -> None:
        with engine.begin() as conn:
            campana_id = base._new(conn)
            conn.execute(text(_INSERT_CONSUMO), _consumo(campana_id, ref=9_000_000_000))
            stored = conn.execute(text("SELECT venta_ref FROM sell_out_consumos")).scalar_one()
        assert stored == 9_000_000_000

    def test_queue_defaults_and_one_row_per_campaign(self, engine: Engine) -> None:
        enqueue = "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)"
        with engine.begin() as conn:
            campana_id = base._new(conn)
            conn.execute(text(enqueue), {"c": campana_id})
            row = conn.execute(text("SELECT enqueued_at, attempts, last_error FROM sell_out_dirty")).one()
        assert (row.attempts, row.last_error) == (0, None)
        assert row.enqueued_at.tzinfo is not None
        base._rejects(engine, enqueue, {"c": campana_id})
        base._rejects(engine, enqueue, {"c": 999_999})

    def test_deleting_a_campaign_cascades_to_its_rows_and_queue(self, engine: Engine) -> None:
        with engine.begin() as conn:
            campana_id = base._new(conn)
            conn.execute(text(_INSERT_CONSUMO), _consumo(campana_id))
            conn.execute(text("INSERT INTO sell_out_dirty (campana_id) VALUES (:c)"), {"c": campana_id})
            conn.execute(text("DELETE FROM sell_out_campanas WHERE id = :c"), {"c": campana_id})
            restantes = conn.execute(
                text("SELECT (SELECT count(*) FROM sell_out_consumos) + (SELECT count(*) FROM sell_out_dirty)")
            ).scalar_one()
        assert restantes == 0

    def test_downgrade_removes_everything_it_created(self, engine: Engine) -> None:
        assert "monto_incluye_iva" in _names(engine, _CAMPANA_COLUMNS)

        _step(engine, base._MIGRATIONS[1], "downgrade")

        assert not ({"sell_out_consumos", "sell_out_dirty"} & _names(engine, _TABLES))
        assert "monto_incluye_iva" not in _names(engine, _CAMPANA_COLUMNS)
        # The previous state still works: a campaign loads as before.
        with engine.begin() as conn:
            assert base._new(conn)


@pytest.mark.postgres
def test_a_row_needs_an_existing_campaign(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(_INSERT_CONSUMO), _consumo(123_456))
