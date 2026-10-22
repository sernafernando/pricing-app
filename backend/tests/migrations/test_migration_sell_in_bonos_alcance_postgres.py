"""Migration `20261114_sell_in_bonos_alcance` (sell-in-sell-out T3e-1, M2a): a bonus
reaches a brand, a category, some models (`sell_in_bono_items`) or one invoice
(`pedido_id`), and pays per invoiced unit or a percentage. Inert: no reader yet,
and the bonus queue's triggers are untouched. Upgrade, downgrade and lock handling
on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation, ForeignKeyViolation, LockNotAvailable, RaiseException, UniqueViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, OperationalError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261114_sell_in_bonos_alcance"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
# `sell_in_bonos_marca` as `20261107_sell_in_bonos_marca` left it, and what it references.
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    """
    CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY,
        marca VARCHAR(100) NOT NULL,
        monto_unit NUMERIC(18, 2) NOT NULL,
        moneda VARCHAR(3) NOT NULL,
        fecha_desde DATE NOT NULL,
        fecha_hasta DATE NOT NULL,
        descripcion TEXT,
        estado VARCHAR(16) NOT NULL DEFAULT 'activa',
        usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE RESTRICT,
        CONSTRAINT ck_sell_in_bonos_marca_moneda CHECK (moneda IN ('ARS', 'USD')),
        CONSTRAINT ck_sell_in_bonos_marca_monto_positivo CHECK (monto_unit > 0),
        CONSTRAINT ck_sell_in_bonos_marca_rango CHECK (fecha_desde <= fecha_hasta),
        CONSTRAINT ck_sell_in_bonos_marca_estado CHECK (estado IN ('activa', 'anulada'))
    )
    """,
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO pedidos_compra VALUES (900), (901)",
]
_COLUMNS = (
    "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'sell_in_bonos_marca' "
    "AND column_name IN ('alcance', 'marca', 'categoria', 'pedido_id', 'tipo', 'monto_unit', 'porcentaje') "
    "ORDER BY column_name"
)
_ITEMS_TABLE = (
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() "
    "AND table_name = 'sell_in_bono_items'"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bonos_alcance_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _bono(engine: Engine, **campos) -> int:
    fila = {"moneda": "USD", "fecha_desde": "2026-10-01", "fecha_hasta": "2026-12-31", "usuario_id": 7}
    fila.update(campos)
    columnas = ", ".join(fila)
    valores = ", ".join(f":{c}" for c in fila)
    with engine.begin() as conn:
        return conn.execute(
            text(f"INSERT INTO sell_in_bonos_marca ({columnas}) VALUES ({valores}) RETURNING id"), fila
        ).scalar_one()


def _item(engine: Engine, bono_id: int, item_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (:b, :i)"), {"b": bono_id, "i": item_id}
        )


def _refused(engine: Engine, error, **campos) -> None:
    with pytest.raises(IntegrityError) as caught:
        _bono(engine, **campos)
    assert isinstance(caught.value.orig, error), caught.value.orig


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_alcance", [], _STUBS) as engine:
        yield engine


@pytest.fixture
def after(before) -> Engine:
    _step(before, "upgrade")
    return before


def test_this_revision_chains_on_the_ads_contributions_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261113_ml_ads_campaign_contributions"
    assert len(script.get_heads()) == 1  # no divergent heads; a later revision may sit on top of this one


@pytest.mark.postgres
def test_upgrade_adds_the_scope_and_kind_and_frees_brand_and_unit_amount(after):
    with after.connect() as conn:
        columns = {name: (nullable, default) for name, nullable, default in conn.execute(text(_COLUMNS))}
        assert conn.execute(text(_ITEMS_TABLE)).scalar() == 1
    assert {name: nullable for name, (nullable, _) in columns.items()} == {
        "alcance": "NO",
        "categoria": "YES",
        "marca": "YES",
        "monto_unit": "YES",
        "pedido_id": "YES",
        "porcentaje": "YES",
        "tipo": "NO",
    }
    assert columns["alcance"][1].startswith("'marca'") and columns["tipo"][1].startswith("'por_unidad'")


@pytest.mark.postgres
def test_upgrade_turns_every_existing_bonus_into_a_brand_bonus_per_unit(before):
    _bono(before, marca="TP-LINK", monto_unit="2")
    _step(before, "upgrade")
    with before.connect() as conn:
        fila = conn.execute(
            text("SELECT alcance, marca, categoria, pedido_id, tipo, monto_unit, porcentaje FROM sell_in_bonos_marca")
        ).one()
    assert tuple(fila) == ("marca", "TP-LINK", None, None, "por_unidad", 2, None)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "campos",
    [
        {"marca": "TP-LINK", "monto_unit": "2"},
        {"alcance": "categoria", "categoria": "Switches", "tipo": "porcentaje", "porcentaje": "2.5"},
        {"alcance": "modelos", "monto_unit": "1.50"},
        {"alcance": "factura", "pedido_id": 900, "tipo": "porcentaje", "porcentaje": "100"},
    ],
)
def test_upgrade_accepts_each_scope_with_its_own_field(after, campos):
    _bono(after, **campos)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "campos",
    [
        {"monto_unit": "2"},  # a brand bonus needs its brand
        {"marca": "TP-LINK", "categoria": "Switches", "monto_unit": "2"},
        {"marca": "TP-LINK", "pedido_id": 900, "monto_unit": "2"},
        {"alcance": "categoria", "monto_unit": "2"},
        {"alcance": "categoria", "categoria": "Switches", "marca": "TP-LINK", "monto_unit": "2"},
        {"alcance": "modelos", "marca": "TP-LINK", "monto_unit": "2"},
        {"alcance": "modelos", "categoria": "Switches", "monto_unit": "2"},
        {"alcance": "factura", "pedido_id": 900, "marca": "TP-LINK", "monto_unit": "2"},
        {"alcance": "marcas", "marca": "TP-LINK", "monto_unit": "2"},
        {"marca": "TP-LINK"},  # per unit without its amount
        {"marca": "TP-LINK", "monto_unit": "0"},
        {"marca": "TP-LINK", "monto_unit": "2", "porcentaje": "2"},
        {"marca": "TP-LINK", "tipo": "porcentaje"},  # a percentage without it
        {"marca": "TP-LINK", "tipo": "porcentaje", "porcentaje": "0"},
        {"marca": "TP-LINK", "tipo": "porcentaje", "porcentaje": "100.0001"},
        {"marca": "TP-LINK", "tipo": "porcentaje", "porcentaje": "2", "monto_unit": "2"},
        {"marca": "TP-LINK", "tipo": "fijo", "monto_unit": "2"},
    ],
)
def test_upgrade_refuses_a_scope_or_kind_without_its_own_field(after, campos):
    _refused(after, CheckViolation, **campos)


@pytest.mark.postgres
def test_an_invoice_bonus_references_its_operation_and_outlives_it(after):
    _refused(after, ForeignKeyViolation, alcance="factura", pedido_id=999, monto_unit="2")
    bono = _bono(after, alcance="factura", pedido_id=900, monto_unit="2")

    with after.begin() as conn:
        conn.execute(text("DELETE FROM pedidos_compra WHERE id = 900"))
        fila = conn.execute(text("SELECT alcance, pedido_id FROM sell_in_bonos_marca WHERE id = :b"), {"b": bono}).one()
    assert tuple(fila) == ("factura", None)  # the worker voids what it generated


@pytest.mark.postgres
def test_a_models_bonus_lists_each_model_once_and_takes_them_along(after):
    bono = _bono(after, alcance="modelos", monto_unit="2")
    _item(after, bono, 4512)
    _item(after, bono, 4513)
    with pytest.raises(IntegrityError) as caught:
        _item(after, bono, 4512)
    assert isinstance(caught.value.orig, UniqueViolation)
    with pytest.raises(IntegrityError) as caught:
        _item(after, 999, 4512)
    assert isinstance(caught.value.orig, ForeignKeyViolation)

    with after.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bonos_marca WHERE id = :b"), {"b": bono})
        assert conn.execute(text("SELECT COUNT(*) FROM sell_in_bono_items")).scalar() == 0


@pytest.mark.postgres
def test_downgrade_restores_the_brand_bonus_table_and_is_idempotent(after):
    _bono(after, marca="TP-LINK", monto_unit="2")

    _step(after, "downgrade")
    _step(after, "downgrade")

    with after.connect() as conn:
        assert conn.execute(text(_ITEMS_TABLE)).scalar() == 0
        columns = {name: nullable for name, nullable, _ in conn.execute(text(_COLUMNS))}
    assert columns == {"marca": "NO", "monto_unit": "NO"}
    _refused(after, CheckViolation, marca="TP-LINK", monto_unit="0")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "campos",
    [
        {"alcance": "categoria", "categoria": "Switches", "monto_unit": "2"},
        {"marca": "TP-LINK", "tipo": "porcentaje", "porcentaje": "2"},
    ],
)
def test_downgrade_refuses_while_a_bonus_only_the_new_schema_can_hold_exists(after, campos):
    _bono(after, **campos)

    with pytest.raises(InternalError) as caught:
        _step(after, "downgrade")
    assert isinstance(caught.value.orig, RaiseException)
    assert "sell_in_bonos_marca" in str(caught.value.orig)
    with after.connect() as conn:
        assert conn.execute(text(_ITEMS_TABLE)).scalar() == 1  # nothing was dropped


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_behind_an_open_writer_it_fails_fast_instead_of_blocking_the_table(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as writer:
        tx = writer.begin()
        writer.exec_driver_sql("LOCK TABLE sell_in_bonos_marca IN ROW EXCLUSIVE MODE")
        try:
            with before.connect() as conn:
                conn.exec_driver_sql("SET statement_timeout = '20s'")  # bounds the test if it does block
                ctx = MigrationContext.configure(conn)
                with pytest.raises(OperationalError) as caught:
                    with ctx.begin_transaction(), Operations.context(ctx):
                        getattr(_module(), step)()
        finally:
            tx.rollback()
    assert isinstance(caught.value.orig, LockNotAvailable)


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step):
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '42s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "42s"
