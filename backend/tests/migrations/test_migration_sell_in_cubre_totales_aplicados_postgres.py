"""Migration `20261114_sell_in_cubre_totales_aplicados` (sell in varias facturas S2): the operation gate also lets in
an operation linked to an active tactical purchase (an applied invoice total), so another invoice linked later queues
it for the re-split; the downgrade restores the previous gate. On a real Postgres, over stub tables."""

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

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261114_sell_in_cubre_totales_aplicados"
_PREVIA = "20261112_tactical_facturas_pendientes"


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_m", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(nombre: str) -> str:
    from app.services.sell_in import bono_queue

    [sentencia] = [s for s in bono_queue.UPGRADE_SQL if nombre in s]
    return sentencia


_STUBS = [
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT NOT NULL, marca TEXT, pedido_id BIGINT,
        estado TEXT NOT NULL DEFAULT 'activa', fecha_desde DATE NOT NULL, fecha_hasta DATE NOT NULL
    )""",
    "CREATE TABLE tactical_facturas_pendientes (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT NOT NULL, "
    "estado TEXT NOT NULL)",
    "CREATE TABLE sell_in_compras (id BIGINT PRIMARY KEY, estado TEXT NOT NULL, tactical_id BIGINT)",
    "CREATE TABLE sell_in_compra_pedidos (id BIGSERIAL PRIMARY KEY, compra_id BIGINT NOT NULL, "
    "pedido_compra_id BIGINT NOT NULL)",
    _sql("FUNCTION sell_in_bono_cubre(p_fecha"),
    *_module().FUNCIONES_DOWN,  # what production runs before this revision
]


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("cubre_totales_apl", [], _STUBS) as engine:
        yield engine


def _cubre(engine: Engine, pedido: int, fecha: str | None = "2026-10-10") -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sell_in_bono_cubre_pedido(CAST(:f AS DATE), :p)"), {"f": fecha, "p": pedido}
        ).scalar()


def _compra(engine: Engine, compra: int, pedido: int, estado: str = "activa", tactical: int | None = 1) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sell_in_compras (id, estado, tactical_id) VALUES (:c, :e, :t)"),
            {"c": compra, "e": estado, "t": tactical},
        )
        conn.execute(
            text("INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (:c, :p)"),
            {"c": compra, "p": pedido},
        )


def test_this_revision_chains_on_the_head_of_main() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261114_marcas_visibles_excepciones"
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.iterate_revisions(heads[0], "base")}


@pytest.mark.postgres
def test_upgrade_gates_in_an_operation_with_an_applied_tactical_total(before) -> None:
    _compra(before, 1, pedido=10)
    _compra(before, 2, pedido=11, estado="anulada")
    _compra(before, 3, pedido=12, tactical=None)  # a purchase loaded on its own
    assert _cubre(before, 10) is False  # before: only a waiting total gated in

    _step(before, "upgrade")

    assert _cubre(before, 10) is True
    assert _cubre(before, 10, None) is False  # still needs the invoice date
    assert _cubre(before, 11) is False  # a voided total does not
    assert _cubre(before, 12) is False  # nor a purchase of no tactical
    assert _cubre(before, 13) is False  # nothing at all: the date gate, as before


@pytest.mark.postgres
def test_downgrade_restores_the_previous_gate(before) -> None:
    _compra(before, 1, pedido=10)
    _step(before, "upgrade")
    _step(before, "downgrade")

    assert _cubre(before, 10) is False


def test_the_live_gate_is_this_revisions_and_the_downgrade_restores_the_previous_one() -> None:
    from app.services.sell_in import bono_queue

    assert {_norm(s) for s in _module().FUNCIONES_UP} <= {_norm(s) for s in bono_queue.UPGRADE_SQL}
    assert {_norm(s) for s in _module().FUNCIONES_DOWN} == {_norm(s) for s in _module(_PREVIA).FUNCIONES_UP}


def _norm(sql: str) -> str:
    return " ".join(sql.split())


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
