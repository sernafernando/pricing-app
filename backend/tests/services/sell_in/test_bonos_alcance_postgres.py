"""The bonus panel's `sin_aplicar` group on Postgres (sell-in-sell-out T18 follow-up), with the live queue
triggers and the real reconcile.

Production case (2026-10-27): bonus "REBATE TPLINK" showed "0 compras · 0 u" while an operation invoiced
inside its range with 21 brand lines had made the worker fail 5 times; the operation showed in no group.
"""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInBonoMarca
from app.services.sell_in import bonos, bonos_alcance
from tests.services.sell_in import _bono_world as b

ERROR = "value too long for type character varying(20)"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_alcance") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _panel(engine: Engine, bono_id: int) -> dict:
    with sessionmaker(bind=engine)() as db:
        return bonos_alcance.alcance(db, db.get(SellInBonoMarca, bono_id), limite=20)


def _aparcar(engine: Engine, tipo: str, ref: int) -> None:
    """What the worker leaves after its 5th failure: the key stays queued with the error."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_bono_dirty (tipo, ref, attempts, last_error) VALUES (:t, :r, 5, :e) "
                "ON CONFLICT (tipo, ref) DO UPDATE SET attempts = 5, last_error = :e"
            ),
            {"t": tipo, "r": ref, "e": ERROR},
        )


def _sin_aplicar(panel: dict) -> list[tuple]:
    return [(i["pedido_id"], i["unidades"], i["motivo"], i["intentos"]) for i in panel["sin_aplicar"]["items"]]


@pytest.mark.postgres
class TestSinAplicar:
    def test_a_parked_in_range_invoice_shows_with_its_error_until_the_reconcile_applies_it(
        self, engine: Engine
    ) -> None:
        bono = b.bono(engine, desde=date(2026, 10, 1), hasta=date(2026, 12, 31))
        pedido = b.pedido(engine, {2964: 15, 2270: 6, 950: 4}, date(2026, 10, 22))
        b.clear_queue(engine)
        _aparcar(engine, "pedido", pedido)

        panel = _panel(engine, bono)
        assert _sin_aplicar(panel) == [(pedido, 21, ERROR, 5)]
        assert panel["alcanzadas"]["total"] == panel["pendientes"]["total"] == panel["fuera_de_rango"]["total"] == 0

        with sessionmaker(bind=engine)() as db:
            bonos.reconciliar(db, bono_ids=[bono])
            db.commit()

        panel = _panel(engine, bono)
        assert panel["sin_aplicar"]["total"] == 0
        assert [(i["pedido_id"], i["unidades"]) for i in panel["alcanzadas"]["items"]] == [(pedido, 21)]

    def test_an_in_range_invoice_without_brand_lines_says_so_and_a_fresh_one_is_en_cola(self, engine: Engine) -> None:
        bono = b.bono(engine)
        sin_lineas = b.pedido(engine, {950: 3}, date(2026, 10, 12))
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO pedido_compra_ingresos (pedido_id, item_id, cantidad_recibida) VALUES (:p, 2964, 8)"),
                {"p": sin_lineas},
            )
        en_cola = b.pedido(engine, {2964: 2}, date(2026, 10, 14))
        fuera = b.pedido(engine, {2964: 9}, date(2026, 11, 2))

        panel = _panel(engine, bono)

        # The triggers queued both operations: queued with no error is still "En cola".
        assert _sin_aplicar(panel) == [
            (en_cola, 2, "En cola", 0),
            (sin_lineas, 0, "Sin líneas de la marca en la factura", 0),
        ]
        assert [i["pedido_id"] for i in panel["fuera_de_rango"]["items"]] == [fuera]
