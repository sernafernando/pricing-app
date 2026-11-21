"""Tienda's Sugerido never pairs a costo SI with a clásica markup still over the list cost (sell-in-costo-si T3 PR 6,
owner L20; orchestrator: "no transient wrong prices ... RED test for the post-deploy/pre-drain state").

Sugerido = cost x (1 + varios) x (1 + clásica + sugerido), with the cost from `lote` and the clásica from the stored
`productos_pricing.markup_calculado`. The deploy's history recompute is the only writer of costo SI steps, and
`queue.drenar` stores them and rewrites the clásica over them (`despues.pricing`) in the same transaction. So:

- after the deploy, before the drain reaches a product: the reader answers its list cost and the stored clásica is over
  that list cost: Sugerido is today's;
- after the drain: both are over costo SI, and the clásica keeps the ML price's net (D4), so cost x (1 + clásica) is
  unchanged and Sugerido moves only by varios x sugerido% x (list - costo SI).

Real drain, real reader, real pricing callback (the PR 4 world). Invented data: P has list cost USD 40 and costo SI
USD 25, USD 1000."""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.productos_shared import computar_precio_sugerido
from app.services import recalcular_markups_service as rms
from app.services.costo_si import lote
from app.services.pricing_calculator import costo_ars_actual
from tests.services.costo_si import _world as w
from tests.services.costo_si.test_despues_pricing_postgres import (  # noqa: F401 (fixture)
    _PRICING,
    P,
    _comision,
    _drenar,
    _fila,
    _pricing,
    _producto_con_costo_si,
    _solo_pricing,
)
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

IVA, VARIOS, SUGERIDO = 21.0, 6.5, 5.0
LISTA_ARS, COSTO_SI_ARS = 40_000.0, 25_000.0


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_tienda_drain", [*w.TABLES, *_PRICING], w.STUBS, after=w.install) as engine:
        yield engine


def _lo_que_lee_tienda(engine: Engine) -> tuple:
    """(cost in pesos, its fuente, stored clásica, Sugerido): what the Tienda listing prices P with."""
    with sessionmaker(bind=engine)() as db:
        costo = costo_ars_actual(db, P, 1000.0)
        fuente = lote.actuales(db, [P], tipo_cambio=1000.0)[P].fuente
    clasica = float(_fila(engine, P)[1])
    sugerido = computar_precio_sugerido(costo, IVA, clasica, SUGERIDO, VARIOS)[0]
    return costo, fuente, clasica, sugerido


def _clasica_sobre_lo_que_lee_hoy(engine: Engine) -> None:
    """The stored clásica as prod has it before the deploy: over the cost the reader answers now (the list cost)."""
    with sessionmaker(bind=engine, autoflush=False)() as db:
        assert rms.recalcular_markups_guardados(db, [P]) == []
        db.commit()


def test_before_the_drain_the_cost_and_the_clasica_are_both_over_the_list_cost(engine: Engine) -> None:
    _comision(engine)
    _producto_con_costo_si(engine)  # P is queued, not drained yet: the deploy just ran
    _pricing(engine, P)
    _clasica_sobre_lo_que_lee_hoy(engine)

    costo, fuente, clasica, sugerido = _lo_que_lee_tienda(engine)

    assert (costo, fuente) == (LISTA_ARS, lote.FUENTE_LISTA)
    factor = 1 + VARIOS / 100
    assert sugerido == pytest.approx(LISTA_ARS * factor * (1 + (clasica + SUGERIDO) / 100))


def test_the_drain_moves_the_cost_and_the_clasica_together(engine: Engine) -> None:
    _comision(engine)
    _producto_con_costo_si(engine)
    _pricing(engine, P)
    _clasica_sobre_lo_que_lee_hoy(engine)
    _, _, clasica_lista, sugerido_antes = _lo_que_lee_tienda(engine)

    assert _drenar(engine).cambiados == 1

    costo, fuente, clasica, sugerido = _lo_que_lee_tienda(engine)
    assert (costo, fuente) == (COSTO_SI_ARS, lote.FUENTE_COSTO_SI)
    # the same ML net over either cost (D4): cost x (1 + clásica) does not move (2-decimal markups)
    assert COSTO_SI_ARS * (1 + clasica / 100) == pytest.approx(LISTA_ARS * (1 + clasica_lista / 100), rel=1e-4)
    # so Sugerido drops only by varios x sugerido% x (list - costo SI), never by the whole sell in
    caida = (1 + VARIOS / 100) * SUGERIDO / 100 * (LISTA_ARS - COSTO_SI_ARS)
    assert sugerido_antes - sugerido == pytest.approx(caida, rel=1e-3)
