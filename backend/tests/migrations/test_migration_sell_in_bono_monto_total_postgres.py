"""Migration `20261108_sell_in_bono_monto_total` (tactical monto total S4): a sell-in cost bonus may be a total split
across its products (`tipo = 'monto_total'`, `monto_total`, `reparto_criterio`) with its fixed shares in
`sell_in_bono_repartos`; its downgrade refuses while such a bonus exists. On a real Postgres, over a stub of
`sell_in_bonos_marca` with the columns and CHECKs the revision rewrites, not the ORM."""

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

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261108_sell_in_bono_monto_total"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, tipo VARCHAR(16) NOT NULL DEFAULT 'por_unidad', monto_unit NUMERIC(18, 2),
        porcentaje NUMERIC(7, 4), base VARCHAR(16) NOT NULL DEFAULT 'factura', tope_unidades INTEGER,
        tope_monto NUMERIC(18, 2),
        CONSTRAINT ck_sell_in_bonos_marca_tipo CHECK (tipo IN ('por_unidad', 'porcentaje')),
        CONSTRAINT ck_sell_in_bonos_marca_monto_segun_tipo CHECK (
            (tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL)
            OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100
                AND monto_unit IS NULL))
    )""",
    "INSERT INTO sell_in_bonos_marca (id, tipo, monto_unit, base) VALUES (1, 'por_unidad', 2.00, 'factura')",
    "INSERT INTO sell_in_bonos_marca (id, tipo, porcentaje, base) VALUES (2, 'porcentaje', 3.0, 'costo_venta')",
    "SELECT setval('sell_in_bonos_marca_id_seq', 10)",
]
_INSERT_TOTAL = (
    "INSERT INTO sell_in_bonos_marca (tipo, monto_total, reparto_criterio, base, tope_unidades, tope_monto, "
    "monto_unit) VALUES ('monto_total', :total, :criterio, :base, :tu, :tm, :mu) RETURNING id"
)


def _total(**overrides) -> dict:
    row = {"total": "1200.00", "criterio": "iguales", "base": "costo_venta", "tu": None, "tm": None, "mu": None}
    row.update(overrides)
    return row


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_monto_total_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :t"
                ),
                {"t": table},
            ).scalars()
        )


def _rejects(engine: Engine, statement: str, params: dict) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(statement), params)


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_total", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_sell_out_split_criterion_and_is_the_only_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261107_sell_out_reparto_criterio"
    assert script.get_heads() == [_REVISION]


@pytest.mark.postgres
def test_upgrade_adds_the_total_its_criterion_and_the_shares_table_and_keeps_existing_bonuses(before) -> None:
    _step(before, "upgrade")

    assert {"monto_total", "reparto_criterio"} <= _columns(before, "sell_in_bonos_marca")
    assert _columns(before, "sell_in_bono_repartos") == {"id", "bono_id", "item_id", "monto"}
    with before.begin() as conn:
        existentes = conn.execute(
            text("SELECT id, tipo, monto_total, reparto_criterio FROM sell_in_bonos_marca ORDER BY id")
        ).all()
        bono = conn.execute(text(_INSERT_TOTAL), _total()).scalar()
        conn.execute(
            text("INSERT INTO sell_in_bono_repartos (bono_id, item_id, monto) VALUES (:b, 2964, 600), (:b, 2270, 600)"),
            {"b": bono},
        )
    assert [tuple(r) for r in existentes] == [(1, "por_unidad", None, None), (2, "porcentaje", None, None)]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "overrides",
    [
        {"total": "0"},
        {"total": "-1200.00"},  # descuento_ars >= 0 stays: a sell-in total is never negative
        {"total": None},
        {"criterio": None},
        {"criterio": "manual"},
        {"base": "factura"},  # an invoice total is a sell-in purchase, not a bonus
        {"tu": 5},
        {"tm": "100.00"},
        {"mu": "2.00"},
    ],
)
def test_a_total_bonus_breaking_a_rule_is_refused_by_the_database(before, overrides) -> None:
    _step(before, "upgrade")

    _rejects(before, _INSERT_TOTAL, _total(**overrides))


@pytest.mark.postgres
def test_a_per_unit_or_percentage_bonus_carries_no_total_nor_criterion(before) -> None:
    _step(before, "upgrade")

    _rejects(before, "UPDATE sell_in_bonos_marca SET monto_total = 100 WHERE id = 1", {})
    _rejects(before, "UPDATE sell_in_bonos_marca SET reparto_criterio = 'iguales' WHERE id = 2", {})


@pytest.mark.postgres
def test_shares_are_positive_one_per_product_and_go_with_their_bonus(before) -> None:
    _step(before, "upgrade")
    with before.begin() as conn:
        bono = conn.execute(text(_INSERT_TOTAL), _total()).scalar()
        conn.execute(text("INSERT INTO sell_in_bono_repartos (bono_id, item_id, monto) VALUES (:b, 2964, 1200)"),
                     {"b": bono})  # fmt: skip
    insert = "INSERT INTO sell_in_bono_repartos (bono_id, item_id, monto) VALUES (:b, :i, :m)"
    _rejects(before, insert, {"b": bono, "i": 2964, "m": "1.00"})
    _rejects(before, insert, {"b": bono, "i": 2270, "m": "0"})
    _rejects(before, insert, {"b": bono, "i": 2270, "m": "-1.00"})
    _rejects(before, insert, {"b": 999, "i": 2270, "m": "1.00"})

    with before.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bonos_marca WHERE id = :b"), {"b": bono})
        assert conn.execute(text("SELECT count(*) FROM sell_in_bono_repartos")).scalar() == 0


@pytest.mark.postgres
def test_downgrade_restores_the_previous_kinds_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _step(before, "downgrade")
    _step(before, "downgrade")

    assert not {"monto_total", "reparto_criterio"} & _columns(before, "sell_in_bonos_marca")
    assert _columns(before, "sell_in_bono_repartos") == set()
    _rejects(before, "INSERT INTO sell_in_bonos_marca (tipo, base) VALUES ('monto_total', 'costo_venta')", {})
    _rejects(before, "INSERT INTO sell_in_bonos_marca (tipo) VALUES ('por_unidad')", {})  # monto_unit needed again
    with before.begin() as conn:
        conn.execute(text("INSERT INTO sell_in_bonos_marca (tipo, monto_unit) VALUES ('por_unidad', 1.50)"))


@pytest.mark.postgres
def test_downgrade_refuses_while_a_total_bonus_exists_and_changes_nothing(before) -> None:
    _step(before, "upgrade")
    with before.begin() as conn:
        conn.execute(text(_INSERT_TOTAL), _total())

    with pytest.raises(Exception, match="monto_total"):
        _step(before, "downgrade")

    assert {"monto_total", "reparto_criterio"} <= _columns(before, "sell_in_bonos_marca")
    assert _columns(before, "sell_in_bono_repartos") == {"id", "bono_id", "item_id", "monto"}


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"
