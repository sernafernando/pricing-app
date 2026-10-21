"""The campaigns service queues what each change can move (sell-in-sell-out T7 S3).

An edit queues the campaign AND the campaigns that shared products with it
BEFORE the edit: afterwards they are no longer linked, so the rebuild of the
edited campaign would not find them. Postgres only (the queue); `_world`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from app.schemas.sell_out import SellOutCampanaIn
from app.services.sell_out import campanas as service
from app.services.sell_out import queue
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
SWITCHES = {"marca": "TP-LINK", "categoria": "Switches"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_campanas_cola") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _data(grupo_ids, **overrides) -> SellOutCampanaIn:
    body = {
        "nombre": "Campaña",
        "fecha_desde": date(2026, 11, 1),
        "fecha_hasta": date(2026, 11, 30),
        "tipo": "por_unidad",
        "monto_unit": "10",
        "moneda": "ARS",
        "grupo_ids": grupo_ids,
        **overrides,
    }
    return SellOutCampanaIn.model_validate(body)


def _queued(engine: Engine) -> list:
    return [row[0] for row in w.queued(engine)]


def test_a_new_campaign_is_queued(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as db:
        cid = service.crear_campana(db, _data([w.grupo(engine, [ROUTERS])]), USUARIO).id

    assert _queued(engine) == [cid]


def test_an_edit_queues_the_campaigns_it_shared_products_with_before_the_edit(engine: Engine) -> None:
    routers, switches = w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES])
    editada = w.campana(engine, [routers])
    compartia = w.campana(engine, [routers])
    w.campana(engine, [switches])  # shares only after the edit: the rebuild of `editada` reaches it
    w.campana(engine, [w.grupo(engine, [{"item_id": 950}])])  # never shares

    with sessionmaker(bind=engine)() as db:
        service.editar_campana(db, editada, _data([switches]), USUARIO)

    assert _queued(engine) == [editada, compartia]


def test_a_void_and_a_payment_rate_queue_the_campaign(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    usd = w.campana(engine, [g], moneda="USD", tc_modo="al_cobro")
    ars = w.campana(engine, [g])

    with sessionmaker(bind=engine)() as db:
        service.definir_tipo_cambio(db, usd, Decimal("1450"), USUARIO)
    assert _queued(engine) == [usd]

    w.clear_queue(engine)
    with sessionmaker(bind=engine)() as db:
        service.anular_campana(db, ars, USUARIO, "baja")
    assert _queued(engine) == [ars]


def test_a_refused_change_queues_nothing(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g])

    with sessionmaker(bind=engine)() as db, pytest.raises(service.SellOutError):
        service.editar_campana(db, cid, _data([g], fecha_hasta=date(2026, 10, 1)), USUARIO)

    assert _queued(engine) == []


@pytest.mark.parametrize("cambio", ["editar", "anular", "tipo_cambio"])
def test_a_campaign_being_rebuilt_refuses_the_change_cleanly_without_storing_it(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, cambio: str
) -> None:
    monkeypatch.setattr(queue, "LOCK_TIMEOUT", "100ms")
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], moneda="USD", tc_modo="al_cobro")
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=cid)
    holder = engine.connect()  # a running `sell_out.drain` batch holds the campaign's queue row
    try:
        holder.execute(text("SELECT 1 FROM sell_out_dirty WHERE campana_id = :c FOR UPDATE"), {"c": cid})
        with sessionmaker(bind=engine)() as db:
            db.execute(text("SET statement_timeout = '3s'"))  # without the lock timeout: fail, never hang
            with pytest.raises(service.SellOutRecalculando, match="se está recalculando"):
                if cambio == "editar":
                    service.editar_campana(db, cid, _data([g], nombre="Otra"), USUARIO)
                elif cambio == "anular":
                    service.anular_campana(db, cid, USUARIO, "baja")
                else:
                    service.definir_tipo_cambio(db, cid, Decimal("1450"), USUARIO)
            assert db.execute(text("SELECT 1")).scalar() == 1  # the session is usable again
            db.commit()  # and holds nothing of the refused change
    finally:
        holder.rollback()
        holder.close()

    with engine.connect() as conn:
        row = conn.execute(text("SELECT nombre, estado, tipo_cambio FROM sell_out_campanas WHERE id = :c"), {"c": cid})
        assert tuple(row.one()) == ("Campaña", "activa", None)  # nothing stored
        assert conn.execute(text("SELECT count(*) FROM auditoria")).scalar() == 0


def test_any_other_queue_error_propagates_as_is(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])

    def _rota(db, ids):
        db.execute(text("SELECT * FROM tabla_que_no_existe"))

    monkeypatch.setattr(queue, "enqueue", _rota)

    with sessionmaker(bind=engine)() as db, pytest.raises(ProgrammingError):
        service.anular_campana(db, cid, USUARIO, "baja")
