"""Migration `20261110_tacticals_marcas` on a real Postgres: a tactical's brands in `tactical_marcas`.

Owner, 2026-11-10: "lo mismo las marcas que se usan para el filtro hay que hacer un selector multiple".
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

from app.models.tactical import TacticalMarca
from tests.services.sell._schema import throwaway_schema

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261110_tacticals_marcas"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE tacticals (id BIGSERIAL PRIMARY KEY, marca VARCHAR(100) NOT NULL, "
    "usuario_id INTEGER NOT NULL REFERENCES usuarios (id))",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO tacticals (marca, usuario_id) VALUES ('TP-LINK', 7), ('MERCUSYS', 7)",
]


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location(f"{_REVISION}_migration", os.path.join(_VERSIONS, f"{_REVISION}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_marcas_mig", (), _STUBS) as engine:
        yield engine


def _marcas(engine: Engine) -> list[tuple[int, str]]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT tactical_id, marca FROM tactical_marcas ORDER BY id"))]


def _ids(engine: Engine) -> list[int]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT id FROM tacticals ORDER BY id")).scalars())


@pytest.mark.postgres
class TestUpgrade:
    def test_every_existing_tactical_keeps_its_single_brand(self, engine: Engine) -> None:
        _step(engine, "upgrade")

        a, b = _ids(engine)
        assert _marcas(engine) == [(a, "TP-LINK"), (b, "MERCUSYS")]

    def test_a_second_run_changes_nothing(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO tacticals (marca, usuario_id) VALUES ('NUEVA', 7)"))

        _step(engine, "upgrade")

        assert len(_marcas(engine)) == 2  # the backfill ran once; the service writes a new tactical's brands

    def test_columns_match_the_model(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.connect() as conn:
            columnas = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'tactical_marcas'"
                    )
                )
            }
            indices = set(
                conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                         "AND tablename = 'tactical_marcas'")
                ).scalars()
            )  # fmt: skip
        assert columnas == {
            "id": ("bigint", "NO"),
            "tactical_id": ("bigint", "NO"),
            "marca": ("character varying", "NO"),
        }
        assert set(columnas) == {c.name for c in TacticalMarca.__table__.columns}
        assert {i.name for i in TacticalMarca.__table__.indexes} <= indices
        assert "uq_tactical_marcas" in indices

    def test_a_brand_is_once_per_tactical_and_goes_with_it(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, _ = _ids(engine)
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO tactical_marcas (tactical_id, marca) VALUES (:t, 'TP-LINK')"), {"t": a})
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tacticals WHERE id = :t"), {"t": a})
        assert [t for t, _ in _marcas(engine)] == [a + 1]


@pytest.mark.postgres
class TestDowngrade:
    def test_drops_the_table_when_every_tactical_has_one_brand(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "downgrade")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('tactical_marcas')")).scalar() is None

    def test_is_refused_while_a_tactical_has_more_than_one_brand(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        a, _ = _ids(engine)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO tactical_marcas (tactical_id, marca) VALUES (:t, 'MERCUSYS')"), {"t": a})

        with pytest.raises(Exception, match="tacticals with more than one brand"):
            _step(engine, "downgrade")
        assert len(_marcas(engine)) == 3
