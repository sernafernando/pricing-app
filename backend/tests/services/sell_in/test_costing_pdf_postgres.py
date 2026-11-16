"""Sell in on ventas por fuera from the PDF reports (VPF T4, S15/S18).

Owner (S18): "sell in / sell out van a aplicar sobre las operaciones que vayamos creando ahí, no se usa nada viejo".
The FIFO reads ventas por fuera only from the PDF lines (canal `pdf`, `venta_ref` = line id), never from the GBP
sync (`ventas_fuera_ml_metricas`). A return is an Nc line (negative quantity); its customer is the client code when
the document has one, else the company and the client name as the detailed report prints it (orchestrator, Q7).

Invented data only (the repo is public).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_costing_pdf") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recompute(engine: Engine, *items: int) -> None:
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, items)
        db.commit()


@pytest.mark.postgres
class TestFuente:
    def test_a_pdf_line_consumes_the_purchase_under_canal_pdf_keyed_by_the_line(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 10, "250000.00")])
        pdf = w.venta(engine, "pdf", 2964, 2, D(2026, 10, 3))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "pdf", pdf, 2964, 2, Decimal("50000.00"))]

    def test_a_gbp_synced_sale_is_not_a_sale_any_more(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 10, "250000.00")])
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))

        _recompute(engine, 2964)

        assert w.consumos(engine) == []

    def test_a_line_without_product_never_consumes(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 10, "250000.00")])
        w.venta(engine, "pdf", None, 2, D(2026, 10, 3))

        _recompute(engine, 2964)

        assert w.consumos(engine) == []

    def test_a_credit_note_line_gives_its_units_back(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 2), cliente=101)
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 4), signo=-1, cliente=101)
        despues = w.venta(engine, "pdf", 2964, 2, D(2026, 10, 5), cliente=102)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "pdf", despues, 2964, 2, Decimal("20.00"))]


@pytest.mark.postgres
class TestClienteDeLaDevolucion:
    """The return's sale is the customer's only earlier sale; the customer is the client code when the document has
    one, else the company + the printed client name (Q7: names are truncated, codes are exact)."""

    def test_by_client_code_two_clients_with_the_same_printed_name_are_apart(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        suya = w.venta(engine, "pdf", 2964, 1, D(2026, 10, 2), cliente=101, cliente_nombre="Comercial Del Sur Dis")
        otra = w.venta(engine, "pdf", 2964, 1, D(2026, 10, 3), cliente=102, cliente_nombre="Comercial Del Sur Dis")
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 4), signo=-1, cliente=101, cliente_nombre="Comercial Del Sur Dis")
        despues = w.venta(engine, "tn", 2964, 1, D(2026, 10, 5))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "pdf", otra, 2964, 1, Decimal("10.00")),
            (linea, "tn", despues, 2964, 1, Decimal("10.00")),
        ]
        assert suya not in [c[2] for c in w.consumos(engine)]

    def test_without_client_code_the_printed_name_matches_the_sale(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        suya = w.venta(engine, "pdf", 2964, 1, D(2026, 10, 2), cliente=None, cliente_nombre="Cliente Norte")
        otra = w.venta(engine, "pdf", 2964, 1, D(2026, 10, 3), cliente=None, cliente_nombre="Cliente Oeste")
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 4), signo=-1, cliente=None, cliente_nombre="Cliente Norte")
        despues = w.venta(engine, "tn", 2964, 1, D(2026, 10, 5))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "pdf", otra, 2964, 1, Decimal("10.00")),
            (linea, "tn", despues, 2964, 1, Decimal("10.00")),
        ]
        assert suya not in [c[2] for c in w.consumos(engine)]

    def test_a_coded_sale_is_not_the_same_customer_as_an_uncoded_return(self, engine: Engine) -> None:
        """No candidate with the return's key: the most recent holder gives the units back."""
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        a = w.venta(engine, "pdf", 2964, 1, D(2026, 10, 2), cliente=101, cliente_nombre="Cliente Norte")
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 3), cliente=102, cliente_nombre="Cliente Oeste")  # loses it
        w.venta(engine, "pdf", 2964, 1, D(2026, 10, 4), signo=-1, cliente=None, cliente_nombre="Cliente Norte")

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "pdf", a, 2964, 1, Decimal("10.00"))]
