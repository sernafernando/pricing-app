"""Migration `20261110_tactical_cobranza` on a real Postgres: one collection record per tactical.

Owner, 2026-11-10: "Hay que hacerle un chequeo de cobranza a los tacticals ... que obligatorio sea la fecha no más."
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.models.tactical import TacticalCobranza
from tests.services.sell._schema import throwaway_schema

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261110_tactical_cobranza"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE tacticals (id BIGSERIAL PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios (id))",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO tacticals (usuario_id) VALUES (7), (7)",
]


def _module():
    spec = importlib.util.spec_from_file_location(f"{_REVISION}_migration", os.path.join(_VERSIONS, f"{_REVISION}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema("tactical_cobranza_mig", (), _STUBS) as engine:
        yield engine


def _ids(engine: Engine) -> list[int]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT id FROM tacticals ORDER BY id")).scalars())


def _cobrar(engine: Engine, tactical_id: int, medio: str = "nota_credito") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tactical_cobranzas (tactical_id, fecha_cobro, medio, usuario_id) "
                "VALUES (:t, '2026-11-10', :m, 7)"
            ),
            {"t": tactical_id, "m": medio},
        )


def _cuantas(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM tactical_cobranzas")).scalar()


def test_revises_the_orchestrator_assigned_head() -> None:
    module = _module()
    assert (module.revision, module.down_revision) == (_REVISION, "20261110_tacticals_marcas")


@pytest.mark.postgres
class TestUpgrade:
    def test_columns_and_indexes_match_the_model(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.connect() as conn:
            columnas = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'tactical_cobranzas'"
                    )
                )
            }
            indices = set(
                conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                         "AND tablename = 'tactical_cobranzas'")
                ).scalars()
            )  # fmt: skip
        assert columnas == {
            "id": ("bigint", "NO"),
            "tactical_id": ("bigint", "NO"),
            "fecha_cobro": ("date", "NO"),
            "medio": ("character varying", "YES"),
            "nc_numero": ("character varying", "YES"),
            "distribuidor": ("character varying", "YES"),
            "otro_detalle": ("character varying", "YES"),
            "observaciones": ("text", "YES"),
            "usuario_id": ("integer", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
            "updated_at": ("timestamp with time zone", "NO"),
        }
        assert set(columnas) == {c.name for c in TacticalCobranza.__table__.columns}
        assert {i.name for i in TacticalCobranza.__table__.indexes} <= indices
        assert "uq_tactical_cobranzas_tactical" in indices

    def test_a_tactical_is_collected_once_and_the_record_goes_with_it(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, b = _ids(engine)
        _cobrar(engine, a)
        with pytest.raises(IntegrityError):
            _cobrar(engine, a)
        _cobrar(engine, b)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tacticals WHERE id = :t"), {"t": a})
        assert _cuantas(engine) == 1

    def test_the_date_is_required_and_the_medium_is_one_of_three(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, b = _ids(engine)
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO tactical_cobranzas (tactical_id, usuario_id) VALUES (:t, 7)"), {"t": a})
        with pytest.raises(IntegrityError):
            _cobrar(engine, a, medio="cheque")
        _cobrar(engine, b, medio="fondo_distribuidor")
        assert _cuantas(engine) == 1

    def test_a_second_run_changes_nothing(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, _ = _ids(engine)
        _cobrar(engine, a)

        _step(engine, "upgrade")

        assert _cuantas(engine) == 1


@pytest.mark.postgres
class TestDowngrade:
    def test_drops_the_table_while_nothing_was_collected(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "downgrade")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('tactical_cobranzas')")).scalar() is None

    def test_is_refused_while_a_collection_exists(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, _ = _ids(engine)
        _cobrar(engine, a)

        with pytest.raises(Exception, match="collection records exist"):
            _step(engine, "downgrade")
        assert _cuantas(engine) == 1
