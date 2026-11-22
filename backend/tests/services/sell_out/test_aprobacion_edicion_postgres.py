"""An engine's own edit of an approved campaign (tacticals approval S4, S5), on Postgres (`_world`): a bulk edit
(`edicion_masiva`) and a split of a `monto_total` campaign (`campanas.repartir`) change money, so an approved
campaign goes back to `pendiente` and is audited as such; a pending one stays pending. The other tests of those
paths keep it approved (`ediciones_aprobadas`) to read what the edit applies."""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auditoria import TipoAccion
from app.services.sell_out import edicion_masiva
from app.services.sell_out import campanas as service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
TP_LINK = {"marca": "TP-LINK"}
MERCUSYS = {"marca": "MERCUSYS"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_aprobacion_edicion") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _db(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False)()


def _estado(engine: Engine, cid: int) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT estado FROM sell_out_campanas WHERE id = :c"), {"c": cid}).scalar_one()


def _a_pendiente(engine: Engine) -> list:
    with engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text("SELECT valores_nuevos FROM auditoria WHERE tipo_accion = :t ORDER BY id"),
                {"t": TipoAccion.TACTICAL_A_PENDIENTE.name},
            )
        ]


def test_a_bulk_date_edit_sends_an_approved_campaign_back_to_pending(engine: Engine) -> None:
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])

    with _db(engine) as db:
        edicion_masiva.editar_campanas(db, [cid], {"fecha_hasta": date(2026, 12, 15)}, USUARIO)

    assert _estado(engine, cid) == "pendiente"
    assert _a_pendiente(engine) == [{"campana_id": cid}]


def test_a_bulk_edit_of_a_pending_campaign_keeps_it_pending_with_no_audit(engine: Engine) -> None:
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], estado="pendiente")

    with _db(engine) as db:
        edicion_masiva.editar_campanas(db, [cid], {"acumulable": False}, USUARIO)

    assert _estado(engine, cid) == "pendiente"
    assert _a_pendiente(engine) == []


def test_a_split_by_criterion_sends_an_approved_monto_total_campaign_back_to_pending(engine: Engine) -> None:
    cid = w.monto_total(engine, [w.grupo(engine, [TP_LINK, MERCUSYS])], "1000.00")

    with _db(engine) as db:
        service.repartir(db, cid, [], USUARIO, None, criterio="iguales")

    assert _estado(engine, cid) == "pendiente"
    assert _a_pendiente(engine) == [{"campana_id": cid}]
