"""Migration `20261203_etiquetas_logistica_historial` (flex-logistica-historial T2, S1): every change of
`etiquetas_envio.logistica_id` leaves one row in `etiquetas_envio_logistica_historial`, written by a row trigger
so no write path can skip it. Who and source come from transaction-local settings; without them the row is
still written, with those fields NULL.

The tests run the migration itself on a throwaway schema holding bare stand-ins for `logisticas` and
`etiquetas_envio`, then change rows with plain SQL UPDATEs (single, bulk, unchanged values).
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import LockNotAvailable
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.services.etiquetas import logistica_historial_sql
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261203_etiquetas_logistica_historial"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "etiquetas_envio_logistica_historial"
_DRIFT = (
    "app/services/etiquetas/logistica_historial_sql.py {} differs from the frozen copy in {}: changing the "
    "module's trigger SQL requires a NEW migration that installs it (then point this test at that migration)"
)
_STUBS = [
    "CREATE TABLE logisticas (id INTEGER PRIMARY KEY)",
    "INSERT INTO logisticas VALUES (1), (2), (3)",
    """CREATE TABLE etiquetas_envio (
        id SERIAL PRIMARY KEY,
        shipping_id VARCHAR(50) UNIQUE NOT NULL,
        logistica_id INTEGER REFERENCES logisticas (id),
        nombre_archivo VARCHAR(255)
    )""",
    "INSERT INTO etiquetas_envio (shipping_id, logistica_id) VALUES ('S1', 1), ('S2', 1), ('S3', NULL), ('S4', 2)",
]


def _scripts() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module():
    spec = importlib.util.spec_from_file_location("etiquetas_logistica_historial_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _historial(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    f"SELECT shipping_id, logistica_anterior_id, logistica_nueva_id, usuario_id, operador_id, origen "
                    f"FROM {_TABLE} ORDER BY id"
                )
            )
        ]


def _exists(engine: Engine, sql: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar() is not None


class TestMigrationGraph:
    def test_this_revision_chains_on_the_tb_item_full_row_revision(self) -> None:
        # Not `get_heads() == [this]`: a later revision must not break this test.
        revision = _scripts().get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == "20261202_sell_in_bono_requeue_auditoria"


class TestFrozenTriggerCopy:
    def test_the_upgrade_installs_exactly_the_module_trigger_sql(self) -> None:
        assert _module().UPGRADE_SQL == logistica_historial_sql.UPGRADE_SQL, _DRIFT.format("UPGRADE_SQL", _REVISION)

    def test_the_downgrade_drops_exactly_the_module_trigger_sql(self) -> None:
        assert _module().DOWNGRADE_SQL == logistica_historial_sql.DOWNGRADE_SQL, _DRIFT.format(
            "DOWNGRADE_SQL", _REVISION
        )


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with throwaway_schema("etq_log_hist", [], _STUBS) as engine:
        yield engine


@pytest.fixture()
def upgraded(engine: Engine) -> Engine:
    _step(engine, "upgrade")
    return engine


@pytest.mark.postgres
class TestHistorial:
    def test_a_change_records_old_new_who_source_and_when(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("SELECT set_config('app.logistica_usuario_id', '7', true)"))
            conn.execute(text("SELECT set_config('app.logistica_operador_id', '12', true)"))
            conn.execute(text("SELECT set_config('app.logistica_origen', 'asignar', true)"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id = 'S1'"))
            ahora = conn.execute(text("SELECT now()")).scalar()

        assert _historial(upgraded) == [("S1", 1, 2, 7, 12, "asignar")]
        with upgraded.connect() as conn:
            assert conn.execute(text(f"SELECT cambiado_en FROM {_TABLE}")).scalar() == ahora

    def test_a_change_to_or_from_null_is_recorded(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 3 WHERE shipping_id = 'S3'"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = NULL WHERE shipping_id = 'S4'"))

        assert _historial(upgraded) == [("S3", None, 3, None, None, None), ("S4", 2, None, None, None, None)]

    def test_the_same_value_or_another_column_records_nothing(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 1 WHERE shipping_id = 'S1'"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = NULL WHERE shipping_id = 'S3'"))
            conn.execute(text("UPDATE etiquetas_envio SET nombre_archivo = 'x.zip'"))

        assert _historial(upgraded) == []

    def test_a_bulk_update_records_one_row_per_changed_label(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("SELECT set_config('app.logistica_usuario_id', '7', true)"))
            conn.execute(text("SELECT set_config('app.logistica_origen', 'masivo', true)"))
            # S4 already has 2: it is not a change.
            conn.execute(
                text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id IN ('S1', 'S2', 'S3', 'S4')")
            )

        assert sorted(_historial(upgraded)) == [
            ("S1", 1, 2, 7, None, "masivo"),
            ("S2", 1, 2, 7, None, "masivo"),
            ("S3", None, 2, 7, None, "masivo"),
        ]

    def test_without_settings_the_row_is_still_written_with_empty_who_and_source(self, upgraded: Engine) -> None:
        with upgraded.connect() as conn:
            # Settings a previous transaction of the same session left behind read back as ''.
            with conn.begin():
                conn.execute(text("SELECT set_config('app.logistica_usuario_id', '7', true)"))
                conn.execute(text("SELECT set_config('app.logistica_origen', 'manual', true)"))
            with conn.begin():
                conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 3 WHERE shipping_id = 'S1'"))

        assert _historial(upgraded) == [("S1", 1, 3, None, None, None)]

    def test_a_malformed_setting_never_blocks_the_change(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("SELECT set_config('app.logistica_usuario_id', 'abc', true)"))
            conn.execute(text("SELECT set_config('app.logistica_operador_id', '99999999999999', true)"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id = 'S1'"))

        assert _historial(upgraded) == [("S1", 1, 2, None, None, None)]

    def test_the_history_outlives_the_label(self, upgraded: Engine) -> None:
        with upgraded.begin() as conn:
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id = 'S1'"))
            conn.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = 'S1'"))

        assert _historial(upgraded) == [("S1", 1, 2, None, None, None)]


@pytest.mark.postgres
class TestUpgradeDowngrade:
    def test_downgrade_drops_the_table_the_trigger_and_the_function(self, upgraded: Engine) -> None:
        _step(upgraded, "downgrade")

        assert not _exists(upgraded, f"SELECT to_regclass('{_TABLE}')")
        assert not _exists(
            upgraded, "SELECT 1 FROM pg_trigger WHERE tgname = 'trg_etiquetas_envio_logistica_historial'"
        )
        assert not _exists(
            upgraded,
            "SELECT 1 FROM pg_proc WHERE pronamespace = current_schema()::regnamespace "
            "AND proname = 'etiquetas_envio_logistica_historial_registrar'",
        )
        with upgraded.begin() as conn:  # the labels keep working without it
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id = 'S1'"))

    @pytest.mark.parametrize("step", ["upgrade", "downgrade"])
    def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(self, engine: Engine, step) -> None:
        """CREATE/DROP TRIGGER needs SHARE ROW EXCLUSIVE on `etiquetas_envio`: behind an open writer it must give
        up (lock_timeout) rather than queue and block every new writer of the table; the deploy retries."""
        if step == "downgrade":
            _step(engine, "upgrade")
        with engine.connect() as writer:
            tx = writer.begin()
            writer.exec_driver_sql("LOCK TABLE etiquetas_envio IN ROW EXCLUSIVE MODE")
            try:
                with engine.connect() as conn:
                    conn.exec_driver_sql("SET statement_timeout = '20s'")  # bounds the test if it does block
                    ctx = MigrationContext.configure(conn)
                    with pytest.raises(OperationalError) as caught:
                        with ctx.begin_transaction(), Operations.context(ctx):
                            getattr(_module(), step)()
            finally:
                tx.rollback()
        assert isinstance(caught.value.orig, LockNotAvailable)

    @pytest.mark.parametrize("step", ["upgrade", "downgrade"])
    def test_it_restores_the_lock_timeout_the_transaction_had(self, engine: Engine, step) -> None:
        """`env.py` runs every pending revision in ONE transaction: a `SET LOCAL` left behind would leak into the
        next revisions, and `= DEFAULT` would clobber what the caller set."""
        if step == "downgrade":
            _step(engine, "upgrade")
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                conn.exec_driver_sql("SET LOCAL lock_timeout = '7s'")
                getattr(_module(), step)()
                assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "7s"
