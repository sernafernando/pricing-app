"""Sell-out list filters on Postgres (campanas-sistema S3): moneda, a period that overlaps the campaign's dates,
and marca, the brand of a product the campaign's groups reach with the campaign rule (`alcance.filtro_alcanza`)."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import campanas as service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("listar_filtros") as engine:
        yield engine


@pytest.fixture()
def ids(engine: Engine) -> Iterator[Callable[..., list[int]]]:
    Session = sessionmaker(bind=engine, autoflush=False)

    def _ids(**filtros: Any) -> list[int]:
        with Session() as db:
            campanas, total = service.listar_campanas(db, service.FiltrosCampanas(**filtros))
            assert total == len(campanas)
            return [c.id for c in campanas]

    yield _ids
    w.clean(engine)


def test_brand_currency_and_period_filters(engine: Engine, ids) -> None:
    tplink = w.grupo(engine, [{"marca": "TP-LINK", "categoria": "Routers"}])
    mercusys = w.grupo(engine, [{"item_id": 950}])
    vacio = w.grupo(engine, [{}])
    nov = w.campana(engine, [tplink])
    dic = w.campana(
        engine, [mercusys], desde=date(2026, 12, 1), hasta=date(2026, 12, 31), moneda="USD", tc_modo="al_cobro"
    )
    ambas = w.campana(engine, [tplink, mercusys], desde=date(2027, 1, 1), hasta=date(2027, 3, 31))
    w.campana(engine, [vacio], desde=date(2027, 1, 1), hasta=date(2027, 3, 31))

    assert ids(marca="TP-LINK") == [ambas, nov]
    assert ids(marca="MERCUSYS") == [ambas, dic]
    assert ids(marca="EPSON") == []
    assert ids(moneda="USD") == [dic]
    assert ids(desde=date(2026, 11, 30), hasta=date(2026, 12, 1)) == [dic, nov]
    assert ids(desde=date(2027, 2, 1), marca="TP-LINK") == [ambas]
