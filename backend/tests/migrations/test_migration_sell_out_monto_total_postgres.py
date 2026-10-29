"""Migration `20261214_sell_out_monto_total` (sell-in-sell-out T26a, S34/S35): a fixed-total sell-out campaign
(positive = credit, negative = deduction), its per-product shares on `sell_out_campana_items`, negative
consumptions, and the downgrade, on a real Postgres.

The "before" world is built by the real earlier sell-out migrations (not the ORM, which already declares this
revision's schema), next to bare stand-ins of the tables they reference."""

from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg2.errors import CheckViolation
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261214_sell_out_monto_total"
_EARLIER = (
    "20261105_sell_out_campanas",
    "20261108_sell_out_consumos",
    "20261111_sell_out_offset_origen",
    "20261207_sell_out_campana_items",
)
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offset_grupos (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",
    "CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE)",
    "CREATE TABLE permisos (id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE, nombre TEXT, descripcion TEXT, "
    "categoria TEXT, orden INTEGER, es_critico BOOLEAN, created_at TIMESTAMPTZ)",
    "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (usuario_id INTEGER, permiso_id INTEGER)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO roles (codigo) VALUES ('ADMIN')",
]
_COLUMNS = (
    "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = :t AND column_name = ANY(:c) ORDER BY column_name"
)
_CONSTRAINTS = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = current_schema()::regnamespace "
    "AND conrelid::regclass::text IN ('sell_out_campanas', 'sell_out_campana_items', 'sell_out_consumos') "
    "ORDER BY conname"
)


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_migration", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str, revision: str = _REVISION) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(revision), step)()


def _build(engine: Engine) -> None:
    for revision in _EARLIER:
        _step(engine, "upgrade", revision)


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("so_monto_total", [], _STUBS, after=_build) as engine:
        yield engine


@pytest.fixture
def after(before) -> Engine:
    _step(before, "upgrade")
    return before


def _campana(engine: Engine, tipo: str = "por_unidad", **cols) -> int:
    values = {"monto_unit": "10", "porcentaje": None, "monto_total": None, "tope_unidades": None, "tope_monto": None}
    if tipo == "porcentaje":
        values.update(monto_unit=None, porcentaje="3")
    elif tipo == "monto_total":
        values.update(monto_unit=None, monto_total="2000000")
    values.update(cols)
    columns = ", ".join(k for k, v in values.items() if v is not None or k in cols)
    params = ", ".join(f":{k}" for k, v in values.items() if v is not None or k in cols)
    with engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, moneda, usuario_id, {columns}) "
                f"VALUES ('C', '2026-11-01', '2026-11-30', :tipo, 'ARS', 7, {params}) RETURNING id"
            ),
            {"tipo": tipo, **{k: v for k, v in values.items() if v is not None or k in cols}},
        ).scalar_one()


def _item(engine: Engine, campana_id: int, item_id: int = 2964, **cols) -> None:
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO sell_out_campana_items (campana_id, item_id, {names}) VALUES (:c, :i, {params})"),
            {"c": campana_id, "i": item_id, **cols},
        )


def _consumo(engine: Engine, campana_id: int, monto: str, venta_ref: int = 1) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "VALUES (:c, 'ml', :v, 2964, '2026-11-05', 1, :m)"
            ),
            {"c": campana_id, "v": venta_ref, "m": monto},
        )


def _check_violation(call) -> None:
    with pytest.raises(IntegrityError) as caught:
        call()
    assert isinstance(caught.value.orig, CheckViolation)


def test_this_revision_chains_on_the_cost_bonus_triggers_revision_and_is_the_only_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261213_sell_in_bono_costo_triggers"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_keeps_existing_campaigns_items_and_consumptions_valid(before) -> None:
    por_unidad = _campana(before)
    porcentaje = _campana(before, "porcentaje", tope_unidades=500)
    _item(before, por_unidad, monto_unit="25.50")
    _consumo(before, porcentaje, "0")

    _step(before, "upgrade")

    with before.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sell_out_campanas WHERE monto_total IS NULL")).scalar() == 2
        assert conn.execute(text("SELECT monto_unit FROM sell_out_campana_items")).scalar_one() == pytest.approx(25.5)
        columns = [tuple(r) for r in conn.execute(text(_COLUMNS), {"t": "sell_out_campanas", "c": ["monto_total"]})]
        assert columns == [("monto_total", "numeric", 18, 2, "YES")]
        columns = [
            tuple(r)
            for r in conn.execute(
                text(_COLUMNS),
                {"t": "sell_out_campana_items", "c": ["monto_unit", "reparto_porcentaje", "reparto_monto"]},
            )
        ]
        assert columns == [
            ("monto_unit", "numeric", 18, 2, "YES"),
            ("reparto_monto", "numeric", 18, 2, "YES"),
            ("reparto_porcentaje", "numeric", 7, 4, "YES"),
        ]
    # The two existing kinds keep exactly their rules.
    _campana(before)
    _campana(before, "porcentaje")
    _check_violation(lambda: _campana(before, monto_unit="0"))
    _check_violation(lambda: _campana(before, "porcentaje", porcentaje="101"))
    _check_violation(lambda: _campana(before, monto_total="5"))  # a por_unidad campaign carries no total
    _check_violation(lambda: _campana(before, "porcentaje", monto_total="5"))


@pytest.mark.postgres
@pytest.mark.parametrize("total", ["2000000", "-13662075", "0.01"])
def test_a_monto_total_campaign_accepts_a_positive_or_negative_total(after, total) -> None:
    campana = _campana(after, "monto_total", monto_total=total)
    with after.connect() as conn:
        guardado = conn.execute(text("SELECT monto_total FROM sell_out_campanas WHERE id = :i"), {"i": campana})
        assert guardado.scalar_one() == Decimal(total)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "cols",
    [
        {"monto_total": "0"},
        {"monto_total": None},
        {"monto_unit": "10"},
        {"porcentaje": "3"},
        {"tope_unidades": 500},
        {"tope_monto": "1000"},
    ],
    ids=["zero", "missing", "unit_amount", "percentage", "unit_cap", "amount_cap"],
)
def test_a_monto_total_campaign_refuses(after, cols) -> None:
    _check_violation(lambda: _campana(after, "monto_total", **cols))


@pytest.mark.postgres
def test_an_unknown_type_is_still_refused(after) -> None:
    _check_violation(lambda: _campana(after, "otro"))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "cols",
    [{"monto_unit": "25"}, {"reparto_porcentaje": "100"}, {"reparto_porcentaje": "0.0001"}, {"reparto_monto": "-5"}],
)
def test_an_item_carries_exactly_one_amount(after, cols) -> None:
    _item(after, _campana(after, "monto_total"), **cols)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "cols",
    [
        {"monto_unit": None},
        {"monto_unit": "25", "reparto_monto": "5"},
        {"reparto_porcentaje": "50", "reparto_monto": "5"},
        {"monto_unit": "0"},
        {"monto_unit": "-1"},
        {"reparto_porcentaje": "0"},
        {"reparto_porcentaje": "-1"},
        {"reparto_porcentaje": "100.0001"},
        {"reparto_monto": "0"},
    ],
    ids=[
        "none",
        "unit_and_fixed",
        "pct_and_fixed",
        "unit_zero",
        "unit_negative",
        "pct_zero",
        "pct_negative",
        "pct_over_100",
        "fixed_zero",
    ],
)
def test_an_item_refuses(after, cols) -> None:
    _check_violation(lambda: _item(after, _campana(after, "monto_total"), **cols))


@pytest.mark.postgres
def test_a_negative_consumption_is_allowed(before) -> None:
    campana = _campana(before)
    _check_violation(lambda: _consumo(before, campana, "-1"))
    _step(before, "upgrade")
    _consumo(before, _campana(before, "monto_total", monto_total="-100"), "-33.33")


@pytest.mark.postgres
def test_downgrade_restores_the_previous_schema_and_is_idempotent(before) -> None:
    with before.connect() as conn:
        previo = [tuple(r) for r in conn.execute(text(_CONSTRAINTS))]
    _step(before, "upgrade")
    _step(before, "upgrade")  # idempotent
    _step(before, "downgrade")
    _step(before, "downgrade")  # idempotent
    with before.connect() as conn:
        assert [tuple(r) for r in conn.execute(text(_CONSTRAINTS))] == previo
        assert conn.execute(text(_COLUMNS), {"t": "sell_out_campanas", "c": ["monto_total"]}).all() == []
        assert (
            conn.execute(
                text(_COLUMNS), {"t": "sell_out_campana_items", "c": ["reparto_porcentaje", "reparto_monto"]}
            ).all()
            == []
        )
        columns = [tuple(r) for r in conn.execute(text(_COLUMNS), {"t": "sell_out_campana_items", "c": ["monto_unit"]})]
        assert columns == [("monto_unit", "numeric", 18, 2, "NO")]


@pytest.mark.postgres
@pytest.mark.parametrize("dato", ["campana", "item", "consumo"])
def test_downgrade_refuses_while_money_rows_need_the_new_schema(after, dato) -> None:
    """It fails loudly instead of deleting a fixed-total campaign, its shares or a negative consumption."""
    por_unidad = _campana(after)
    if dato == "campana":
        _campana(after, "monto_total")
    elif dato == "item":
        # A share on a por_unidad campaign: the schema allows it (the service refuses it), the downgrade must not.
        _item(after, por_unidad, reparto_monto="5")
    else:
        _consumo(after, por_unidad, "-1")

    with pytest.raises((InternalError, ProgrammingError, IntegrityError)) as caught:
        _step(after, "downgrade")
    assert "20261214_sell_out_monto_total" in str(caught.value)
    with after.connect() as conn:  # nothing was changed
        assert conn.execute(text(_COLUMNS), {"t": "sell_out_campanas", "c": ["monto_total"]}).all() != []


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
