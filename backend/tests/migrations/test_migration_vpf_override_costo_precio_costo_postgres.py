"""Migration `20261124_vpf_override_costo_precio_costo` (owner L3/L4): a stored manual cost becomes the unit Precio
Costo, so `costo_unitario` is divided by 1.065 and the line's precio_costo (and its Costo D) stays the same when the
fix is re-applied; no-op without overrides; downgrade multiplies back. Real Postgres; every value is INVENTED."""

from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

from app.models.venta_fuera_pdf import VentaFueraLineaOverride
from app.services.ventas_fuera_pdf.overrides import precio_costo_manual
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "alembic",
    "versions",
    "20261124_vpf_override_costo_precio_costo.py",
)


def _step(engine: Engine, step: str) -> None:
    spec = importlib.util.spec_from_file_location("vpf_override_costo_precio_costo_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "vpf_override_costo_mig",
        [VentaFueraLineaOverride.__table__],
        ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)"],
    ) as engine:
        yield engine


def _insert(engine: Engine, renglon: int, costo: str | None, cantidad: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ventas_fuera_linea_overrides (empresa, tipo, letra, punto_venta, numero, renglon, "
                "costo_unitario, articulo, cantidad, precio, estado) "
                "VALUES ('EMPRESA EJEMPLO SA', 'Fc', 'A', 9, 1, :r, :c, 'ARTICULO EJEMPLO', :q, 1000, 'aplicado')"
            ),
            {"r": renglon, "c": costo, "q": cantidad},
        )


def _costos(engine: Engine) -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT renglon, costo_unitario FROM ventas_fuera_linea_overrides")).all())


def test_without_overrides_both_directions_are_a_no_op(engine: Engine) -> None:
    _step(engine, "upgrade")
    assert _costos(engine) == {}
    _step(engine, "downgrade")
    assert _costos(engine) == {}


def test_upgrade_divides_by_1_065_keeping_the_line_cost_and_downgrade_multiplies_back(engine: Engine) -> None:
    _insert(engine, 1, "1065", "1")
    _insert(engine, 2, "900", "2")  # old rule: precio_costo = 900 x 2 / 1.065 = 1690.14
    _insert(engine, 3, None, "1")  # a product-only fix

    _step(engine, "upgrade")

    costos = _costos(engine)
    assert costos == {1: Decimal("1000.000000"), 2: Decimal("845.070423"), 3: None}
    assert precio_costo_manual(costos[2], Decimal("2")) == Decimal("1690.14")

    _step(engine, "downgrade")

    assert _costos(engine) == {1: Decimal("1065.000000"), 2: Decimal("900.000000"), 3: None}
