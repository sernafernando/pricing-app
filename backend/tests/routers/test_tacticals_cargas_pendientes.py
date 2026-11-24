# ruff: noqa: F811 - the fixtures imported from the neighbour test modules are taken as parameters
"""The approval inbox of the Tacticals list (tacticals approval S11, S12): `GET /api/tacticals/cargas-pendientes`
lists the bonuses, purchases and campaigns loaded on their own that wait for approval (S11: "no pending item may be
unreachable from the UI"), and `GET /api/tacticals` answers `pendientes_aprobacion`, the count of what waits for
approval, next to KPIs that leave pending tacticals out (S12). Postgres test database (`_pg_app`: the KPIs read what
costo SI took off the invoices, Postgres-only SQL); the queries in `tests/services/test_tacticals_aprobacion_postgres.py`."""

from __future__ import annotations

import pytest

from tests.routers._pg_app import engine  # noqa: F401 - the fixture, by name
from tests.routers.test_sell_out_campanas import BASE as CAMPANAS
from tests.routers.test_sell_out_campanas import _crear as crear_campana
from tests.routers.test_sell_out_campanas import grupos  # noqa: F401 - fixture
from tests.routers.test_tacticals import BASE, _body, productos, sell_out  # noqa: F401 - fixtures

pytestmark = pytest.mark.postgres

PENDIENTES = f"{BASE}/cargas-pendientes"


def test_a_campaign_loaded_on_its_own_is_listed_until_it_is_approved(
    client, grupos, sell_out, rol_admin, grant_permiso, admin_user
) -> None:
    campana = crear_campana(client, sell_out, grupos)

    resp = client.get(PENDIENTES, headers=sell_out)

    assert resp.status_code == 200, resp.text
    [carga] = resp.json()["items"]
    assert (carga["origen"], carga["id"], carga["nombre"], carga["moneda"]) == (
        "sell_out_campana", campana["id"], campana["nombre"], campana["moneda"],
    )  # fmt: skip
    assert (carga["fecha_desde"], carga["fecha_hasta"]) == (campana["fecha_desde"], campana["fecha_hasta"])
    assert (carga["usuario_id"], carga["usuario_nombre"]) == (admin_user.id, admin_user.nombre)
    grant_permiso(rol_admin, "tacticals.aprobar")
    assert client.post(f"{CAMPANAS}/{campana['id']}/aprobar", headers=sell_out).status_code == 200
    assert client.get(PENDIENTES, headers=sell_out).json()["items"] == []


def test_it_lists_only_the_kinds_the_caller_may_read(client, grupos, sell_out) -> None:
    crear_campana(client, sell_out, grupos)

    assert client.get(PENDIENTES, params={"tipo": "sell_in"}, headers=sell_out).status_code == 403
    assert len(client.get(PENDIENTES, params={"tipo": "sell_out"}, headers=sell_out).json()["items"]) == 1


def test_without_reading_either_kind_it_is_a_403(client, admin_auth_headers) -> None:
    assert client.get(PENDIENTES, headers=admin_auth_headers).status_code == 403


def test_the_list_counts_what_waits_for_approval_and_its_kpis_leave_it_out(client, productos, grupos, sell_out) -> None:
    assert client.post(BASE, json=_body(), headers=sell_out).status_code == 201
    crear_campana(client, sell_out, grupos)

    lista = client.get(BASE, params={"estado": "vigentes"}, headers=sell_out).json()

    assert lista["pendientes_aprobacion"] == 2  # the pending tactical and the standalone campaign
    assert lista["kpis"]["pendientes"] == {"cantidad": 0, "sin_tope": 0, "montos": []}
    todos = client.get(BASE, headers=sell_out).json()
    assert (todos["total"], todos["kpis"]["pendientes"]["cantidad"]) == (1, 0)  # listed, but no money yet


def test_a_tactical_is_still_read_by_its_id(client, productos, sell_out) -> None:
    creado = client.post(BASE, json=_body(), headers=sell_out).json()

    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["id"] == creado["id"]


def test_an_offset_loaded_on_its_own_is_listed_until_it_is_approved(
    client, db, sell_out, rol_admin, grant_permiso, admin_user
) -> None:
    """S10 + S11: `POST /offsets-ganancia` stores it pending; it waits in the inbox, with the sell out loads."""
    grant_permiso(rol_admin, "config.editar_constantes")
    oferta = {"marca": "EPSON", "fecha_desde": "2026-11-01", "tipo_offset": "monto_fijo", "monto": 50}
    offset = client.post("/api/offsets-ganancia", json=oferta, headers=sell_out).json()

    [carga] = client.get(PENDIENTES, headers=sell_out).json()["items"]

    assert (carga["origen"], carga["id"], carga["nombre"], carga["marca"]) == (
        "offset_ganancia", offset["id"], "Offset EPSON", "EPSON",
    )  # fmt: skip
    assert (carga["moneda"], carga["fecha_desde"], carga["fecha_hasta"]) == ("ARS", "2026-11-01", None)
    assert (carga["usuario_id"], carga["usuario_nombre"]) == (admin_user.id, admin_user.nombre)
    assert client.get(BASE, headers=sell_out).json()["pendientes_aprobacion"] == 1
    grant_permiso(rol_admin, "tacticals.aprobar")
    assert client.post(f"/api/offsets-ganancia/{offset['id']}/aprobar", headers=sell_out).status_code == 200
    assert client.get(PENDIENTES, headers=sell_out).json()["items"] == []
    assert client.get(BASE, headers=sell_out).json()["pendientes_aprobacion"] == 0


def test_every_pending_load_is_reachable_by_pages(client, db, sell_out, admin_user) -> None:
    """S11: "no pending item may be unreachable from the UI" (verifier A2): past one page the rest is on the next
    ones, and `total` counts them all."""
    from datetime import date as _date

    from app.models.offset_ganancia import OffsetGanancia

    db.add_all(
        OffsetGanancia(
            marca="EPSON", tipo_offset="monto_fijo", monto=i, fecha_desde=_date(2026, 11, 1), estado="pendiente",
            usuario_id=admin_user.id,
        )
        for i in range(1, 202)
    )  # fmt: skip
    db.commit()

    primera = client.get(PENDIENTES, params={"page_size": 200}, headers=sell_out).json()
    segunda = client.get(PENDIENTES, params={"page": 2, "page_size": 200}, headers=sell_out).json()

    assert (len(primera["items"]), primera["total"], primera["page"], primera["page_size"]) == (200, 201, 1, 200)
    assert (len(segunda["items"]), segunda["total"]) == (1, 201)
    ids = [c["id"] for c in primera["items"] + segunda["items"]]
    assert len(set(ids)) == 201 and ids == sorted(ids, reverse=True)  # newest first, each once
    porDefecto = client.get(PENDIENTES, headers=sell_out).json()
    assert (len(porDefecto["items"]), porDefecto["total"], porDefecto["page_size"]) == (50, 201, 50)
    assert client.get(PENDIENTES, params={"page_size": 201}, headers=sell_out).status_code == 422
