"""Migration `20261206_offsets_migracion_pendientes` (sell-in-sell-out T22a): the review table of the
legacy offsets the migration script could not turn into sell in / sell out, its downgrade, on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import NotNullViolation, UniqueViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261206_offsets_migracion_pendientes"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "offsets_migracion_pendientes"
_COLUMNS = (
    "SELECT column_name, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t ORDER BY ordinal_position"
)


def _module():
    spec = importlib.util.spec_from_file_location("offsets_migracion_pendientes_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _insert(engine: Engine, **values) -> None:
    row = {"offset_id": 1, "motivo": "Monto fijo", **values}
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {_TABLE} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"), row)


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("offsets_pendientes", [], []) as engine:
        yield engine


def test_this_revision_chains_on_the_divergence_quarantine_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261205_ml_ops_divergence_quarantine"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_creates_the_review_table_with_the_offset_detail(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = dict(conn.execute(text(_COLUMNS), {"t": _TABLE}).all())
    assert columns == {
        "id": "NO",
        "offset_id": "NO",
        "tipo_offset": "YES",
        "descripcion": "YES",
        "marca": "YES",
        "categoria": "YES",
        "subcategoria_id": "YES",
        "item_id": "YES",
        "grupo_id": "YES",
        "monto": "YES",
        "porcentaje": "YES",
        "moneda": "YES",
        "tipo_cambio": "YES",
        "fecha_desde": "YES",
        "fecha_hasta": "YES",
        "max_unidades": "YES",
        "max_monto_usd": "YES",
        "aplica_ml": "YES",
        "aplica_fuera": "YES",
        "aplica_tienda_nube": "YES",
        "usuario_id": "YES",
        "motivo": "NO",
        "avisos": "YES",
        "registrado_en": "NO",
    }
    _insert(before, monto=10000.5, fecha_hasta=None)
    with before.connect() as conn:
        assert conn.execute(text(f"SELECT registrado_en IS NOT NULL FROM {_TABLE}")).scalar() is True


@pytest.mark.postgres
def test_one_row_per_offset_and_a_reason_is_required(before) -> None:
    _step(before, "upgrade")
    _insert(before)

    with pytest.raises(IntegrityError) as caught:
        _insert(before, motivo="otra vez")
    assert isinstance(caught.value.orig, UniqueViolation)

    with pytest.raises(IntegrityError) as caught:
        _insert(before, offset_id=2, motivo=None)
    assert isinstance(caught.value.orig, NotNullViolation)


@pytest.mark.postgres
def test_a_row_outlives_its_offset_no_foreign_key(before) -> None:
    # The review is about offsets someone may delete afterwards: the detail must stay.
    _step(before, "upgrade")
    _insert(before, offset_id=999999)

    with before.connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar() == 1


@pytest.mark.postgres
def test_downgrade_drops_the_table_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text("SELECT to_regclass(:t)"), {"t": _TABLE}).scalar() is None
