"""Migration `20261212_sell_in_bono_costo` (sell-in-sell-out T25a): a sell-in bonus may be a % of the cost recorded on
the sale, with no purchase or invoice (`base = 'costo_venta'`), with an 'incluye IVA' flag and the legacy offset it was
migrated from; `sell_in_bono_consumos` keeps what each sale got; a change of the new fields queues the bonus; its
downgrade, on a real Postgres. `sell_in_bonos_marca` is a stub with the columns the update trigger reads, not the ORM."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261212_sell_in_bono_costo"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TABLE = "sell_in_bonos_marca"
_STUBS = [
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT, marca TEXT, categoria TEXT, pedido_id BIGINT, tipo TEXT,
        monto_unit NUMERIC(18, 2), porcentaje NUMERIC(7, 4), moneda TEXT, fecha_desde DATE, fecha_hasta DATE,
        estado TEXT, usuario_id INTEGER, descripcion TEXT, tope_unidades INTEGER, tope_monto NUMERIC(18, 2)
    )""",
    # Bonus 1: by invoice (every existing bonus); bonus 2: what a cost bonus may be.
    "INSERT INTO sell_in_bonos_marca (id, alcance, marca, tipo, porcentaje, moneda) "
    "VALUES (1, 'marca', 'LENOVO', 'por_unidad', NULL, 'USD'), (2, 'marca', 'TP-LINK', 'porcentaje', 2.71, 'ARS')",
    "CREATE TABLE encolados (bono_id BIGINT)",
    # Stands in for the real queue function (20261115): records which bonus was queued.
    """CREATE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $$
    BEGIN INSERT INTO encolados VALUES (NEW.id); RETURN NULL; END $$ LANGUAGE plpgsql""",
]
_COLUMNS = (
    "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t "
    "AND column_name IN ('base', 'incluye_iva', 'offset_origen_id') ORDER BY column_name"
)
_CONSUMO = (
    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars) "
    "VALUES (:bono, :canal, :ref, 2964, '2026-10-10', :u, :d)"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_costo_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _update(engine: Engine, sql: str, bono: int = 2) -> list:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM encolados"))
        conn.execute(text(f"UPDATE {_TABLE} SET {sql} WHERE id = :b"), {"b": bono})
        return [r[0] for r in conn.execute(text("SELECT bono_id FROM encolados"))]


def _consumo(engine: Engine, bono: int = 2, canal: str = "ml", ref: int = 1, u: int = 1, d: str = "10.00") -> None:
    with engine.begin() as conn:
        conn.execute(text(_CONSUMO), {"bono": bono, "canal": canal, "ref": ref, "u": u, "d": d})


def _violation(caught) -> type:
    return type(caught.value.orig)


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_costo", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_total_gauss_known_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261208_ml_sale_lines_tg_unknown"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_adds_the_columns_and_every_existing_bonus_stays_an_invoice_bonus(before) -> None:
    _step(before, "upgrade")

    with before.connect() as conn:
        columns = {r[0]: tuple(r[1:]) for r in conn.execute(text(_COLUMNS), {"t": _TABLE})}
        existentes = conn.execute(text(f"SELECT id, base, incluye_iva, offset_origen_id FROM {_TABLE} ORDER BY id"))
        existentes = [tuple(r) for r in existentes]
    assert columns["base"][:2] == ("character varying", "NO") and "factura" in columns["base"][2]
    assert columns["incluye_iva"][:2] == ("boolean", "NO") and "false" in columns["incluye_iva"][2]
    assert columns["offset_origen_id"] == ("integer", "YES", None)
    assert existentes == [(1, "factura", False, None), (2, "factura", False, None)]


@pytest.mark.postgres
def test_a_cost_bonus_is_a_percentage_in_pesos_over_a_brand_category_or_models(before) -> None:
    _step(before, "upgrade")

    assert _update(before, "base = 'costo_venta', incluye_iva = true, offset_origen_id = 9") == [2]
    for alcance, campos in (("categoria", "marca = NULL, categoria = 'Routers'"), ("modelos", "categoria = NULL")):
        assert _update(before, f"alcance = '{alcance}', {campos}") == [2]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "sql",
    [
        "base = 'otra'",
        "base = 'costo_venta', tipo = 'por_unidad', monto_unit = 5, porcentaje = NULL",
        "base = 'costo_venta', moneda = 'USD'",
        "base = 'costo_venta', alcance = 'factura', marca = NULL",
        "incluye_iva = true",  # the flag only means something on a cost bonus
    ],
    ids=["base-desconocida", "por-unidad", "en-dolares", "factura", "iva-en-bono-por-factura"],
)
def test_what_a_cost_bonus_cannot_be(before, sql) -> None:
    _step(before, "upgrade")
    with pytest.raises(IntegrityError) as caught:
        _update(before, sql)
    assert _violation(caught) is CheckViolation


@pytest.mark.postgres
def test_one_bonus_per_legacy_offset(before) -> None:
    _step(before, "upgrade")
    _update(before, "base = 'costo_venta', offset_origen_id = 9")

    with pytest.raises(IntegrityError) as caught:
        _update(before, "offset_origen_id = 9", bono=1)
    assert _violation(caught) is UniqueViolation


@pytest.mark.postgres
def test_the_consumption_table_keeps_one_row_per_bonus_and_sale(before) -> None:
    _step(before, "upgrade")

    _consumo(before, ref=1)
    _consumo(before, canal="fuera", ref=1)  # same reference, another channel
    _consumo(before, bono=1, ref=1)  # same sale, another bonus
    with pytest.raises(IntegrityError) as caught:
        _consumo(before, ref=1, d="20.00")
    assert _violation(caught) is UniqueViolation
    for kw in ({"canal": "otro", "ref": 2}, {"ref": 3, "u": 0}, {"ref": 4, "d": "-0.01"}):
        with pytest.raises(IntegrityError) as caught:
            _consumo(before, **kw)
        assert _violation(caught) is CheckViolation
    with pytest.raises(IntegrityError) as caught:
        _consumo(before, bono=99, ref=5)
    assert _violation(caught) is ForeignKeyViolation

    with before.begin() as conn:
        conn.execute(text(f"DELETE FROM {_TABLE} WHERE id = 2"))  # bonuses are voided, never deleted: cascade anyway
        assert conn.execute(text("SELECT bono_id FROM sell_in_bono_consumos")).scalars().all() == [1]


@pytest.mark.postgres
def test_a_change_of_the_new_fields_queues_the_bonus_and_an_unrelated_change_does_not(before) -> None:
    _step(before, "upgrade")

    assert _update(before, "base = 'costo_venta'") == [2]
    assert _update(before, "incluye_iva = true") == [2]
    assert _update(before, "incluye_iva = true") == []  # nothing changed
    assert _update(before, "offset_origen_id = 11") == []  # provenance only: the reconcile does not read it
    assert _update(before, "descripcion = 'otra'") == []
    assert _update(before, "tope_monto = 3000") == [2]  # the fields queued before still queue


@pytest.mark.postgres
def test_downgrade_drops_everything_restores_the_trigger_and_both_steps_are_idempotent(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _update(before, "base = 'costo_venta', incluye_iva = true")
    _consumo(before)
    _step(before, "downgrade")
    _step(before, "downgrade")

    with before.connect() as conn:
        assert conn.execute(text(_COLUMNS), {"t": _TABLE}).all() == []
        assert conn.execute(text("SELECT to_regclass('sell_in_bono_consumos')")).scalar() is None
    assert _update(before, "tope_monto = 10") == [2]
    assert _update(before, "descripcion = 'otra'") == []


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '17s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "17s"


def test_the_live_update_trigger_is_this_revisions() -> None:
    """`bono_queue.UPGRADE_SQL` (what the test worlds install) and this revision's bonus update trigger are the same."""
    from app.services.sell_in import bono_queue

    vivo = [s for s in bono_queue.UPGRADE_SQL if "CREATE TRIGGER trg_sell_in_bono_bonos_update" in s]
    assert len(vivo) == 1
    assert " ".join(vivo[0].split()) == " ".join(_module()._trigger(con_costo=True).split())
