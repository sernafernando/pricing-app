"""`alembic revision --autogenerate` must never propose dropping the Costo SI T4 snapshots: tables without a model,
created on purpose by `20261128_costo_si_t4_recalculo` as the recalc's safety net. Every other table is compared as
before."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, Table

from app.core.alembic_autogenerate import incluir


def _tabla(nombre: str) -> Table:
    return Table(nombre, MetaData(), Column("id", Integer, primary_key=True))


def test_a_t4_snapshot_in_the_database_is_left_out() -> None:
    nombre = "costo_si_t4_respaldo_ml_ventas_metricas"
    assert incluir(_tabla(nombre), nombre, "table", True, None) is False


@pytest.mark.parametrize(
    "nombre,tipo,reflejada",
    [
        ("ml_ventas_metricas", "table", True),  # a real table without a model: still proposed, as before
        ("costo_si_pasos", "table", False),
        ("costo_si_t4_respaldo_x", "index", True),  # not a table
    ],
)
def test_everything_else_is_compared_as_before(nombre: str, tipo: str, reflejada: bool) -> None:
    assert incluir(_tabla(nombre), nombre, tipo, reflejada, None) is True
