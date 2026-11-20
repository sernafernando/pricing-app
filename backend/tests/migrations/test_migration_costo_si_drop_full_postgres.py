"""Migration `20261125_costo_si_drop_full`: drops the two tables that kept Mercado Libre's Full operations, unused since
the Full is rebuilt from the ML stock and sales the app already stores (owner L11). The downgrade puts them back as
`20261125_costo_si` created them, so that migration's own downgrade still runs."""

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

from tests.migrations.test_migration_costo_si_postgres import _NUEVAS, _tablas
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261125_costo_si_drop_full"
_PREVIA = "20261125_costo_si"
_FULL = {"costo_si_full_operaciones", "costo_si_full_cobertura"}


def _step(engine: Engine, revision: str, step: str) -> None:
    path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{revision}.py")
    spec = importlib.util.spec_from_file_location(f"{revision}_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _indices(engine: Engine) -> set:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename LIKE 'costo_si_full%'"
                )
            )
        }


@pytest.fixture
def con_costo_si() -> Iterator[Engine]:
    tablas = [t for t in w.TABLES if t.name not in _NUEVAS]
    with throwaway_schema("costo_si_drop_full", tablas, w.STUBS) as engine:
        _step(engine, _PREVIA, "upgrade")
        yield engine


def test_it_chains_on_costo_si_and_is_the_single_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_REVISION).down_revision == _PREVIA
    assert script.get_heads() == [_REVISION]


def test_no_model_maps_the_dropped_tables() -> None:
    import app.models  # noqa: F401  (registers every model on Base)
    from app.core.database import Base

    assert not _FULL & set(Base.metadata.tables)


@pytest.mark.postgres
def test_upgrade_drops_the_full_tables_and_downgrade_restores_them(con_costo_si: Engine) -> None:
    assert _FULL <= _tablas(con_costo_si)

    _step(con_costo_si, _REVISION, "upgrade")

    assert not _FULL & _tablas(con_costo_si)
    assert _NUEVAS - _FULL <= _tablas(con_costo_si)  # the rest of costo SI is untouched

    _step(con_costo_si, _REVISION, "downgrade")

    assert _FULL <= _tablas(con_costo_si)
    assert _indices(con_costo_si) == {
        "costo_si_full_operaciones_pkey",
        "ix_costo_si_full_operaciones_inv_fecha",
        "costo_si_full_cobertura_pkey",
    }
    _step(con_costo_si, _PREVIA, "downgrade")  # the previous downgrade still finds what it drops
    assert not _NUEVAS & _tablas(con_costo_si)
