"""Migration `20261111_sell_in_bono_marca_categoria` (SISO S3): a brand bonus may carry a category; the other scopes
keep their rule; the downgrade restores the old CHECK. On a real Postgres, over a stub table with the old CHECK."""

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
_REVISION = "20261111_sell_in_bono_marca_categoria"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_VIEJO = (
    "(alcance = 'marca' AND marca IS NOT NULL AND categoria IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'categoria' AND categoria IS NOT NULL AND marca IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'modelos' AND marca IS NULL AND categoria IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'factura' AND marca IS NULL AND categoria IS NULL)"
)


def _module():
    spec = importlib.util.spec_from_file_location("sell_in_bono_marca_categoria_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STUBS = [
    f"""CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT, marca TEXT, categoria TEXT, pedido_id BIGINT,
        estado TEXT NOT NULL DEFAULT 'activa', fecha_desde DATE NOT NULL DEFAULT '2026-10-01',
        fecha_hasta DATE NOT NULL DEFAULT '2026-10-31',
        CONSTRAINT ck_sell_in_bonos_marca_campos_segun_alcance CHECK ({_VIEJO})
    )""",
    "CREATE TABLE sell_in_bono_items (bono_id BIGINT, item_id INTEGER)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY)",
    "INSERT INTO sell_in_bonos_marca (id, alcance, marca) VALUES (1, 'marca', 'TP-LINK')",
    *_module().FUNCIONES_DOWN,  # what production runs before this revision
]


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _insertar(engine: Engine, alcance: str, marca, categoria) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sell_in_bonos_marca (alcance, marca, categoria) VALUES (:a, :m, :c)"),
            {"a": alcance, "m": marca, "c": categoria},
        )


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_marca_cat", [], _STUBS) as engine:
        yield engine


def test_this_revision_chains_on_the_pedido_compra_facturas_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261110_pedido_compra_facturas"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_lets_a_brand_bonus_carry_a_category_and_keeps_the_other_rules(before) -> None:
    with pytest.raises(IntegrityError):
        _insertar(before, "marca", "TP-LINK", "Routers")

    _step(before, "upgrade")

    _insertar(before, "marca", "TP-LINK", "Routers")
    _insertar(before, "marca", "TP-LINK", None)
    with pytest.raises(IntegrityError):
        _insertar(before, "categoria", "TP-LINK", "Routers")
    with pytest.raises(IntegrityError):
        _insertar(before, "marca", None, "Routers")
    with before.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sell_in_bonos_marca")).scalar() == 3


@pytest.mark.postgres
def test_downgrade_restores_the_old_rule(before) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")

    with pytest.raises(IntegrityError):
        _insertar(before, "marca", "TP-LINK", "Routers")
    _insertar(before, "marca", "TP-LINK", None)


def _cubre(engine: Engine, categoria: str) -> bool:
    """Whether the queue's gate sees a TP-LINK product of `categoria`, invoiced on 2026-10-15, as covered."""
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sell_in_bono_cubre_producto('2026-10-15', 1, 2964, 'TP-LINK', :c)"), {"c": categoria}
        ).scalar()


@pytest.mark.postgres
def test_upgrade_makes_the_queue_gate_read_the_category_of_a_brand_line(before) -> None:
    # A brand line with a category under the old gate: the old CHECK is re-added NOT VALID only to seed the row.
    with before.begin() as conn:
        conn.execute(
            text("ALTER TABLE sell_in_bonos_marca DROP CONSTRAINT ck_sell_in_bonos_marca_campos_segun_alcance")
        )
        conn.execute(text("DELETE FROM sell_in_bonos_marca"))
        conn.execute(
            text("INSERT INTO sell_in_bonos_marca (alcance, marca, categoria) VALUES ('marca', 'TP-LINK', 'Routers')")
        )
        conn.execute(
            text(
                "ALTER TABLE sell_in_bonos_marca ADD CONSTRAINT ck_sell_in_bonos_marca_campos_segun_alcance "
                f"CHECK ({_VIEJO}) NOT VALID"
            )
        )
    assert _cubre(before, "Switches") is True  # the old gate ignored the category

    _step(before, "upgrade")

    assert _cubre(before, "Switches") is False
    assert _cubre(before, "Routers") is True


def test_the_live_module_functions_are_this_revisions_and_the_downgrade_restores_the_previous_ones() -> None:
    from app.services.sell_in import bono_queue

    module = _module()
    vivos = {_norm(s) for s in bono_queue.UPGRADE_SQL}
    assert {_norm(s) for s in module.FUNCIONES_UP} <= vivos
    versions = os.path.join(_BACKEND_ROOT, "alembic", "versions")

    def _previa(revision: str, nombre: str) -> list:
        spec = importlib.util.spec_from_file_location(f"{revision}_m", os.path.join(versions, f"{revision}.py"))
        previa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(previa)
        return [s for s in getattr(previa, nombre) if "CREATE OR REPLACE FUNCTION" in s]

    previos = {_norm(s) for s in _previa("20261115_sell_in_bono_queue_alcance", "_TRIGGERS_UP")}
    previos |= {_norm(s) for s in _previa("20261213_sell_in_bono_costo_triggers", "PRODUCTO_UP")}
    assert {_norm(s) for s in module.FUNCIONES_DOWN} <= previos


def _norm(sql: str) -> str:
    return " ".join(sql.split())
