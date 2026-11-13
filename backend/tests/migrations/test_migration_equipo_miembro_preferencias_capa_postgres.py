"""Migration `20261113_equipo_miembro_preferencias_capa` (pubml-capa-default S4): each member's own layer preferences
on `equipo_miembro`. Existing memberships keep today's behavior (no default = global, the global reference shown);
downgrade drops both columns.

Runs the migration itself on a throwaway schema holding a bare stand-in of the table (production's columns).
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
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261113_equipo_miembro_preferencias_capa"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    """CREATE TABLE equipo_miembro (
        id SERIAL PRIMARY KEY,
        equipo_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        rol VARCHAR(20) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    )""",
    "INSERT INTO equipo_miembro (equipo_id, usuario_id, rol) VALUES (1, 10, 'admin'), (2, 10, 'miembro')",
]


def _module():
    spec = importlib.util.spec_from_file_location("equipo_miembro_preferencias_capa_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _columns(engine: Engine) -> set:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'equipo_miembro'"
                )
            ).scalars()
        )


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with throwaway_schema("equipo_prefs_mig", [], _STUBS) as eng:
        yield eng


def test_the_revision_chains_on_the_current_head() -> None:
    # Not `get_heads() == [this]`: compras_048 (and later revisions) chain on top.
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script_dir = ScriptDirectory.from_config(config)
    assert script_dir.get_revision(_REVISION).down_revision == "20261113_permiso_mejores_ofertas_pms"
    (head,) = script_dir.get_heads()
    ancestors = {rev.revision for rev in script_dir.walk_revisions(base="base", head=head)}
    assert _REVISION in ancestors


def test_upgrade_keeps_todays_behavior_on_existing_and_new_rows(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO equipo_miembro (equipo_id, usuario_id, rol) VALUES (3, 11, 'miembro')"))
        rows = conn.execute(text("SELECT por_defecto, mostrar_referencia_global FROM equipo_miembro ORDER BY id")).all()

    assert [tuple(r) for r in rows] == [(False, True)] * 3


def test_a_user_holds_at_most_one_default(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("UPDATE equipo_miembro SET por_defecto = true WHERE equipo_id = 1"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE equipo_miembro SET por_defecto = true WHERE equipo_id = 2"))


def test_downgrade_drops_both_columns(engine) -> None:
    _step(engine, "upgrade")
    _step(engine, "downgrade")

    assert _columns(engine) == {"id", "equipo_id", "usuario_id", "rol", "created_at"}
