"""A `monto_total` campaign's split through the campaigns service on Postgres (T26c, S34): every change of the shares
queues the campaign for `sell_out.drain` in the same transaction, and the campaign summary reports what its rows do
not carry (`reparto.resumen_monto_total`) once the rebuild wrote them. `_world`, like the queue tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaItemIn
from app.services.sell_out import campanas as service
from app.services.sell_out import resumen
from app.services.sell_out.asignacion import recalcular
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
TP_LINK = {"marca": "TP-LINK"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_reparto_api") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _share(item_id: int, **values) -> SellOutCampanaItemIn:
    return SellOutCampanaItemIn.model_validate({"item_id": item_id, **values})


def test_a_split_change_queues_the_campaign(engine: Engine) -> None:
    campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00")
    w.clear_queue(engine)

    with sessionmaker(bind=engine)() as db:
        service.repartir(db, campana, [_share(2964, reparto_porcentaje="60")], USUARIO, None)

    assert [row[0] for row in w.queued(engine)] == [campana]


def test_a_refused_split_queues_nothing(engine: Engine) -> None:
    campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00")
    w.clear_queue(engine)

    with sessionmaker(bind=engine)() as db, pytest.raises(service.SellOutError):
        service.repartir(db, campana, [_share(2964, reparto_monto="1000.01")], USUARIO, None)

    assert w.queued(engine) == []


def test_the_summary_reports_assigned_without_sales_and_unassigned(engine: Engine) -> None:
    campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00")
    w.reparto(engine, campana, 2964, porcentaje="60")  # sells: its 600 go to its rows
    w.reparto(engine, campana, 2270, monto="100.00")  # no sale: "Asignado sin ventas"
    w.venta(engine, "ml", 2964, 2, date(2026, 11, 2))
    with sessionmaker(bind=engine)() as db:
        recalcular(db, [campana])
        db.commit()

    with sessionmaker(bind=engine)() as db:
        [out] = resumen.serializar(db, [db.get(SellOutCampana, campana)])

    assert out["resumen"]["monto"] == Decimal("600.00")
    assert out["resumen"]["reparto"] == {
        "asignado": Decimal("700.00"),
        "asignado_sin_ventas": Decimal("100.00"),
        "sin_asignar": Decimal("300.00"),
        "motivo": None,
    }
