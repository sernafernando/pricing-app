"""`sell_dirty` writers for ventas por fuera from the PDF reports (VPF T4): canal `fuera`, keyed by the line id (orchestrator, L20).

The GBP sync (`ventas_fuera_ml_metricas`) queues nothing any more: it is not a sale source (owner, S18).
Invented data only (the repo is public).
"""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text

from tests.services.sell_in import _world as w

D = date(2026, 10, 3)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_dirty_pdf") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _vaciar_cola(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))


def _sql(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _cola(engine: Engine) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 2"))]


@pytest.mark.postgres
class TestLineas:
    def test_a_new_line_with_product_queues_it(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D)

        assert _cola(engine) == [("fuera", ref, 2964)]

    def test_a_line_without_product_queues_nothing(self, engine: Engine) -> None:
        w.venta(engine, "fuera", None, 1, D)

        assert _cola(engine) == []

    def test_deleting_the_document_queues_its_line_with_its_product(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D)
        _vaciar_cola(engine)

        w.delete_venta(engine, "fuera", ref)

        assert _cola(engine) == [("fuera", ref, 2964)]

    def test_a_line_that_gets_its_product_queues_it(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", None, 1, D)

        _sql(engine, "UPDATE ventas_fuera_operacion_lineas SET item_id = 2270 WHERE id = :r", r=ref)

        assert _cola(engine) == [("fuera", ref, 2270)]

    def test_a_line_that_loses_its_product_queues_it_under_the_old_one(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D)
        _vaciar_cola(engine)

        _sql(engine, "UPDATE ventas_fuera_operacion_lineas SET item_id = NULL WHERE id = :r", r=ref)

        assert _cola(engine) == [("fuera", ref, 2964)]

    def test_rewriting_a_line_with_the_same_values_queues_nothing(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D)
        _vaciar_cola(engine)

        _sql(engine, "UPDATE ventas_fuera_operacion_lineas SET item_id = item_id, precio = precio WHERE id = :r", r=ref)

        assert _cola(engine) == []


@pytest.mark.postgres
class TestDocumento:
    def test_a_client_code_filled_by_a_later_summary_queues_the_lines(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D, cliente=None)
        sin_producto = w.venta(engine, "fuera", None, 1, D, cliente=None)
        _vaciar_cola(engine)

        _sql(engine, "UPDATE ventas_fuera_operaciones SET cliente_codigo = '101'")

        assert _cola(engine) == [("fuera", ref, 2964)]
        assert sin_producto not in [r[1] for r in _cola(engine)]

    def test_another_column_of_the_document_queues_nothing(self, engine: Engine) -> None:
        w.venta(engine, "fuera", 2964, 1, D)
        _vaciar_cola(engine)

        _sql(engine, "UPDATE ventas_fuera_operaciones SET saldo = 10, cliente = cliente")

        assert _cola(engine) == []


@pytest.mark.postgres
class TestSincronizacionGbp:
    def test_a_synced_gbp_sale_queues_nothing(self, engine: Engine) -> None:
        ref = w.venta(engine, "gbp", 2964, 1, D)
        _sql(engine, "UPDATE ventas_fuera_ml_metricas SET cantidad = 3 WHERE it_transaction = :r", r=ref)
        w.delete_venta(engine, "gbp", ref)

        assert _cola(engine) == []
