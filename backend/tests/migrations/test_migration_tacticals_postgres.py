"""Migration `20261105_tacticals` (tacticals T1) on a real Postgres: the `tacticals` header, `tactical_id` on the three
engines' tables (nullable, FK RESTRICT, indexed, no backfill), `offset_grupos.oculto`, the cost-bonus CHECK that now
takes a per-unit amount, and the guarded downgrade.

The "before" world is bare stand-ins of the tables it alters, with 20261212's cost-bonus CHECK as it is in production."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError

from tests.services.sell._schema import throwaway_schema

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261105_tacticals"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE FUNCTION sell_out_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$",
    "CREATE TABLE sell_out_campanas (id BIGSERIAL PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE sell_in_compras (id BIGSERIAL PRIMARY KEY)",
    "CREATE TABLE offset_grupos (id SERIAL PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE sell_in_bonos_marca (id BIGSERIAL PRIMARY KEY, base VARCHAR(16) NOT NULL, tipo VARCHAR(16) NOT NULL, "
    "moneda VARCHAR(3) NOT NULL, alcance VARCHAR(16) NOT NULL, incluye_iva BOOLEAN NOT NULL DEFAULT false, "
    "monto_unit NUMERIC(18, 2), porcentaje NUMERIC(7, 4), "
    "CONSTRAINT ck_sell_in_bonos_marca_costo_venta CHECK ((base = 'factura' AND NOT incluye_iva) OR (base = "
    "'costo_venta' AND tipo = 'porcentaje' AND moneda = 'ARS' AND alcance IN ('marca', 'categoria', 'modelos'))))",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO sell_out_campanas (nombre) VALUES ('Campaña vieja')",
    "INSERT INTO offset_grupos (nombre) VALUES ('Grupo viejo')",
    "INSERT INTO sell_in_compras DEFAULT VALUES",
    "INSERT INTO sell_in_bonos_marca (base, tipo, moneda, alcance, porcentaje) "
    "VALUES ('costo_venta', 'porcentaje', 'ARS', 'marca', 3)",
]
_LINEAS = ("sell_out_campanas", "sell_in_bonos_marca", "sell_in_compras")
_POR_UNIDAD = (
    "INSERT INTO sell_in_bonos_marca (base, tipo, moneda, alcance, monto_unit) "
    "VALUES ('costo_venta', 'por_unidad', 'ARS', 'marca', 36)"
)
_TACTICAL = (
    "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, usuario_id) "
    "VALUES ('sell_out', 'Tactical noviembre', 'MARCA A', '2026-11-01', '2026-11-30', 'USD', 'al_cobro', 7) RETURNING id"
)


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
    with throwaway_schema("tacticals_mig", (), _STUBS) as engine:
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
    def test_every_line_table_gets_a_null_tactical_id_and_groups_are_visible(self, engine: Engine) -> None:
        _step(engine, "upgrade")

        for tabla in _LINEAS:
            assert tuple(_columna(engine, tabla, "tactical_id"))[:2] == ("bigint", "YES")
            with engine.connect() as conn:
                assert conn.execute(text(f"SELECT tactical_id FROM {tabla}")).scalars().all() == [None]
        assert tuple(_columna(engine, "offset_grupos", "oculto"))[:2] == ("boolean", "NO")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT oculto FROM offset_grupos")).scalars().all() == [False]

    def test_a_child_carries_its_line_number_only_with_its_tactical(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            tactical = conn.execute(text(_TACTICAL)).scalar_one()
        for tabla in _LINEAS:
            assert tuple(_columna(engine, tabla, "tactical_linea"))[:2] == ("smallint", "YES")
            with engine.begin() as conn:
                conn.execute(text(f"UPDATE {tabla} SET tactical_id = :t, tactical_linea = 2"), {"t": tactical})
            for valores in ("tactical_id = NULL", "tactical_linea = NULL", "tactical_linea = 0"):
                with pytest.raises(IntegrityError):
                    with engine.begin() as conn:
                        conn.execute(text(f"UPDATE {tabla} SET {valores}"))

    def test_a_tactical_with_a_line_cannot_be_deleted(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            tactical = conn.execute(text(_TACTICAL)).scalar_one()
            conn.execute(text("UPDATE sell_out_campanas SET tactical_id = :t, tactical_linea = 1"), {"t": tactical})

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM tacticals"))

    def test_the_header_refuses_a_usd_fixed_rate_without_its_rate(self, engine: Engine) -> None:
        _step(engine, "upgrade")

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_TACTICAL.replace("'al_cobro'", "'fijo'")))

    def test_a_cost_bonus_may_be_per_unit_after_it_and_not_before(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_POR_UNIDAD))

        _step(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text(_POR_UNIDAD))
        with pytest.raises(IntegrityError):  # still ARS only
            with engine.begin() as conn:
                conn.execute(text(_POR_UNIDAD.replace("'ARS'", "'USD'")))

    def test_the_updated_at_trigger_moves_it(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            tactical = conn.execute(text(_TACTICAL)).scalar_one()
        with engine.begin() as conn:
            conn.execute(text("UPDATE tacticals SET nombre = 'Otro' WHERE id = :t"), {"t": tactical})
            creado, cambiado = conn.execute(text("SELECT created_at, updated_at FROM tacticals")).one()
        assert cambiado > creado  # set by the trigger in a later transaction

    def test_it_runs_twice(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "upgrade")

        assert _columna(engine, "sell_in_compras", "tactical_id") is not None


@pytest.mark.postgres
class TestDowngrade:
    def test_it_is_refused_while_a_tactical_exists(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text(_TACTICAL))

        with pytest.raises(InternalError, match="tacticals exist"):
            _step(engine, "downgrade")
        assert _columna(engine, "sell_out_campanas", "tactical_id") is not None

    def test_it_is_refused_while_a_per_unit_cost_bonus_exists(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(text(_POR_UNIDAD))

        with pytest.raises(InternalError, match="per-unit cost bonuses exist"):
            _step(engine, "downgrade")

    def test_otherwise_it_drops_everything_and_restores_the_check(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _step(engine, "downgrade")

        for tabla in _LINEAS:
            assert _columna(engine, tabla, "tactical_id") is None
            assert _columna(engine, tabla, "tactical_linea") is None
        assert _columna(engine, "offset_grupos", "oculto") is None
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('tacticals')")).scalar() is None
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_POR_UNIDAD))
