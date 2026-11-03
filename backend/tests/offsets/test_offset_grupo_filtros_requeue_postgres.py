"""Editing a group's filters through the offsets API re-queues the sell-out campaigns using it
(sell-in-sell-out T30, money rule (a)).

The `offset_grupo_filtros` statement triggers (`sell_out.triggers`) queue the ACTIVE campaigns of the
group; this proves the API endpoints the Grupos panel calls (add, remove, replace) go through them.
Postgres only, in the throwaway sell-out world with only those triggers installed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Iterator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.api.endpoints.offsets_ganancia import _filtros, _grupos
from app.core.database import get_db
from app.main import app
from app.services.sell_out import triggers
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("grupo_filtros_api") as engine:
        with engine.begin() as conn:
            for statement in triggers.UPGRADE_SQL:
                conn.exec_driver_sql(statement)
        yield engine


@pytest.fixture()
def api(engine: Engine, monkeypatch) -> Iterator[TestClient]:
    Session = sessionmaker(bind=engine)

    def _db():
        with Session() as session:
            yield session

    monkeypatch.setattr(_filtros, "verificar_permiso", lambda db, user, codigo: codigo == "config.editar_constantes")
    monkeypatch.setattr(_grupos, "verificar_permiso", lambda db, user, codigo: codigo == "config.editar_constantes")
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        w.clean(engine)
        w.clear_queue(engine)


def _queued(engine: Engine) -> List[int]:
    return [cid for cid, _, _ in w.queued(engine)]


def _setup(engine: Engine):
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    activas = sorted([w.campana(engine, [grupo]), w.campana(engine, [grupo])])
    w.campana(engine, [grupo], estado="anulada")
    w.campana(engine, [w.grupo(engine, [{"marca": "MERCUSYS"}])])  # another group
    w.clear_queue(engine)
    return grupo, activas


def test_adding_a_filter_queues_every_active_campaign_of_the_group(api: TestClient, engine: Engine) -> None:
    grupo, activas = _setup(engine)

    resp = api.post(f"/api/offset-grupos/{grupo}/filtros", json={"item_id": 950})

    assert resp.status_code == 200, resp.text
    assert _queued(engine) == activas


def test_removing_a_filter_queues_every_active_campaign_of_the_group(api: TestClient, engine: Engine) -> None:
    grupo, activas = _setup(engine)
    filtro_id = api.get(f"/api/offset-grupos/{grupo}/filtros").json()[0]["id"]
    w.clear_queue(engine)

    resp = api.delete(f"/api/offset-grupos/{grupo}/filtros/{filtro_id}")

    assert resp.status_code == 200, resp.text
    assert _queued(engine) == activas


def test_replacing_the_filters_queues_every_active_campaign_of_the_group(api: TestClient, engine: Engine) -> None:
    grupo, activas = _setup(engine)

    resp = api.put(f"/api/offset-grupos/{grupo}/filtros", json=[{"categoria": "Routers"}])

    assert resp.status_code == 200, resp.text
    assert _queued(engine) == activas


def test_the_reach_preview_counts_on_postgres_and_queues_nothing(api: TestClient, engine: Engine) -> None:
    grupo, _ = _setup(engine)
    filtro_id = api.get(f"/api/offset-grupos/{grupo}/filtros").json()[0]["id"]
    w.clear_queue(engine)

    agregar = api.post(f"/api/offset-grupos/{grupo}/alcance-previo", json={"agregar": {"marca": "MERCUSYS"}})
    quitar = api.post(f"/api/offset-grupos/{grupo}/alcance-previo", json={"quitar_filtro_id": filtro_id})

    assert agregar.status_code == 200, agregar.text
    assert agregar.json() == {"antes": 2, "despues": 3}
    assert quitar.json() == {"antes": 2, "despues": 0}
    assert _queued(engine) == []
    assert [f["id"] for f in api.get(f"/api/offset-grupos/{grupo}/filtros").json()] == [filtro_id]
