"""Migration `20261107_tacticals_tiendas` on a real Postgres: store-scope columns and `tactical_tiendas`."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261107_tacticals_tiendas"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE FUNCTION sell_out_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$",
    "CREATE TABLE ml_tiendas_oficiales ("
    "store_id BIGINT PRIMARY KEY, nombre VARCHAR(100) NOT NULL, clave VARCHAR(50), "
    "orden INTEGER NOT NULL DEFAULT 0, activa BOOLEAN NOT NULL DEFAULT true, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    # Minimal tacticals header as left by 20261105 (before this revision's columns).
    "CREATE TABLE tacticals ("
    "id BIGSERIAL PRIMARY KEY, tipo VARCHAR(16) NOT NULL, nombre VARCHAR(200) NOT NULL, "
    "marca VARCHAR(100) NOT NULL, referencia VARCHAR(200), fecha_desde DATE NOT NULL, fecha_hasta DATE NOT NULL, "
    "moneda VARCHAR(3) NOT NULL, tc_modo VARCHAR(16), tipo_cambio NUMERIC(18, 6), "
    "incluye_iva BOOLEAN NOT NULL DEFAULT false, acumulable BOOLEAN NOT NULL DEFAULT true, nota TEXT, "
    "estado VARCHAR(16) NOT NULL DEFAULT 'activo', usuario_id INTEGER NOT NULL REFERENCES usuarios (id), "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave) VALUES (57997, 'GaussOnline', 'gauss')",
    "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id) "
    "VALUES ('sell_out', 'Viejo', 'MARCA A', '2026-11-01', '2026-11-30', 'ARS', 7)",
]


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location(
        f"{_REVISION}_migration", os.path.join(_VERSIONS, f"{_REVISION}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_tiendas_mig", (), _STUBS) as engine:
        yield engine


def _columna(engine: Engine, tabla: str, columna: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
            ),
            {"t": tabla, "c": columna},
        ).first()


@pytest.mark.postgres
class TestUpgrade:
    def test_existing_tacticals_default_to_all_stores(self, engine: Engine) -> None:
        _step(engine, "upgrade")

        assert tuple(_columna(engine, "tacticals", "todas_tiendas"))[:2] == ("boolean", "NO")
        assert tuple(_columna(engine, "tacticals", "tope_compartido"))[:2] == ("boolean", "NO")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT todas_tiendas, tope_compartido FROM tacticals")).one() == (True, False)

    def test_oficial_row_needs_store_id_and_channels_forbid_it(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.connect() as conn:
            tid = conn.execute(text("SELECT id FROM tacticals")).scalar_one()

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', NULL)"),
                    {"t": tid},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'fuera', 57997)"
                    ),
                    {"t": tid},
                )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES "
                    "(:t, 'oficial', 57997), (:t, 'fuera', NULL)"
                ),
                {"t": tid},
            )

    def test_oficial_store_is_unique_per_tactical(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            tid = conn.execute(text("SELECT id FROM tacticals")).scalar_one()
            conn.execute(
                text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', 57997)"),
                {"t": tid},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', 57997)"
                    ),
                    {"t": tid},
                )

    def test_it_runs_twice(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "upgrade")
        assert _columna(engine, "tactical_tiendas", "store_id") is not None


@pytest.mark.postgres
class TestDowngrade:
    def test_it_drops_the_scope(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "downgrade")

        assert _columna(engine, "tacticals", "todas_tiendas") is None
        assert _columna(engine, "tacticals", "tope_compartido") is None
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('tactical_tiendas')")).scalar() is None
