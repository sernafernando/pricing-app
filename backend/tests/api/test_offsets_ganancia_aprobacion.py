"""Legacy profit offsets wait for approval (tacticals approval S10, orchestrator: "offsets POST and
migrar_offsets_a_sell_out.py create 'pendiente'"). `POST /api/offsets-ganancia` stores a new offset `pendiente`: it
applies to nothing (no rentabilidad, no consumption) until someone with `tacticals.aprobar` approves it through
`POST /api/offsets-ganancia/{id}/aprobar`. A money edit of an approved offset sends it back; a description edit does
not. Existing offsets keep applying. SQLite."""

from datetime import date

import pytest

from app.models.offset_ganancia import OffsetGanancia
from app.models.producto import ProductoERP
from tests.api.test_offsets_ganancia_crud import _grant_editar_constantes  # noqa: F401 - autouse fixture

BASE = "/api/offsets-ganancia"
APROBAR = "tacticals.aprobar"
OFFSET = {"marca": "MarcaTest", "fecha_desde": "2026-01-01", "tipo_offset": "monto_fijo", "monto": 50}


@pytest.fixture()
def aprobador(rol_admin, grant_permiso, admin_auth_headers):
    grant_permiso(rol_admin, APROBAR)
    return admin_auth_headers


def _crear(client, headers, **cambios) -> dict:
    resp = client.post(BASE, json={**OFFSET, **cambios}, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _estados(db) -> list[str]:
    db.expire_all()
    return [o.estado for o in db.query(OffsetGanancia).order_by(OffsetGanancia.id)]


def test_a_new_offset_waits_for_approval(client, db, admin_auth_headers) -> None:
    creado = _crear(client, admin_auth_headers)

    assert creado["estado"] == "pendiente"
    assert (creado["marca"], creado["monto"], creado["tipo_offset"]) == ("MarcaTest", 50, "monto_fijo")  # as before
    [listado] = client.get(BASE, headers=admin_auth_headers).json()
    assert (listado["id"], listado["estado"]) == (creado["id"], "pendiente")


def test_several_products_at_once_all_wait(client, db, admin_auth_headers) -> None:
    db.add_all(ProductoERP(item_id=i, codigo=str(i), descripcion=f"Producto {i}", activo=True) for i in (11, 12))
    db.commit()
    resp = client.post(BASE, json={**OFFSET, "marca": None, "item_ids": [11, 12]}, headers=admin_auth_headers)

    assert resp.json() == {"mensaje": "Se crearon 2 offsets", "cantidad": 2}  # the answer as before
    assert _estados(db) == ["pendiente", "pendiente"]


def test_the_current_offsets_leave_a_pending_one_out(client, db, admin_auth_headers) -> None:
    aplicado = OffsetGanancia(marca="Vieja", tipo_offset="monto_fijo", monto=10, fecha_desde=date(2026, 1, 1))
    db.add(aplicado)
    db.commit()
    _crear(client, admin_auth_headers)

    vigentes = client.get(BASE, params={"solo_vigentes": True}, headers=admin_auth_headers).json()

    assert [(o["id"], o["estado"]) for o in vigentes] == [(aplicado.id, "activa")]  # an existing one still applies


def test_approving_needs_the_permission_and_happens_once(client, db, admin_auth_headers, rol_admin, grant_permiso):
    creado = _crear(client, admin_auth_headers)
    assert client.post(f"{BASE}/{creado['id']}/aprobar", headers=admin_auth_headers).status_code == 403

    grant_permiso(rol_admin, APROBAR)
    resp = client.post(f"{BASE}/{creado['id']}/aprobar", headers=admin_auth_headers)

    assert (resp.status_code, resp.json()["estado"]) == (200, "activa")
    segunda = client.post(f"{BASE}/{creado['id']}/aprobar", headers=admin_auth_headers)
    assert segunda.status_code == 409
    assert "ya está aprobado" in segunda.json()["error"]["message"]
    assert client.post(f"{BASE}/999999/aprobar", headers=admin_auth_headers).status_code == 404


def test_a_money_edit_sends_an_approved_offset_back_and_the_description_does_not(client, db, aprobador) -> None:
    creado = _crear(client, aprobador)
    client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)

    nombre = client.put(f"{BASE}/{creado['id']}", json={"descripcion": "Rebate Q4"}, headers=aprobador)
    assert (nombre.status_code, nombre.json()["estado"], nombre.json()["descripcion"]) == (200, "activa", "Rebate Q4")

    monto = client.put(f"{BASE}/{creado['id']}", json={"monto": 80}, headers=aprobador)
    assert (monto.status_code, monto.json()["estado"], monto.json()["monto"]) == (200, "pendiente", 80)


@pytest.mark.parametrize(
    "cambio",
    [{"fecha_hasta": "2026-12-31"}, {"max_unidades": 5}, {"aplica_ml": False}, {"categoria": "Routers"}],
    ids=["dates", "cap", "channel", "scope"],
)
def test_dates_caps_channels_and_scope_are_money_too(client, db, aprobador, cambio) -> None:
    creado = _crear(client, aprobador)
    client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)

    assert client.put(f"{BASE}/{creado['id']}", json=cambio, headers=aprobador).json()["estado"] == "pendiente"


def test_an_edit_of_an_offset_loaded_before_approval_existed_sends_it_back(client, db, admin_auth_headers) -> None:
    viejo = OffsetGanancia(marca="Vieja", tipo_offset="monto_fijo", monto=10, fecha_desde=date(2026, 1, 1))
    db.add(viejo)
    db.commit()

    resp = client.put(f"{BASE}/{viejo.id}", json={"monto": 20}, headers=admin_auth_headers)

    assert (resp.status_code, resp.json()["estado"]) == (200, "pendiente")


# --- production sessions do not autoflush (`app/core/database.py`: SessionLocal(autoflush=False)) ----------------------


def test_a_money_edit_is_stored_without_autoflush(client, db, aprobador) -> None:
    """The verifier's probe (S10, B1): the send-back reloads the row locked; the edit must be flushed before, or the
    new amount is thrown away and only `pendiente` is stored."""
    creado = _crear(client, aprobador)
    assert client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador).status_code == 200
    db.autoflush = False  # as SessionLocal in production

    resp = client.put(f"{BASE}/{creado['id']}", json={"monto": 80}, headers=aprobador)

    assert resp.status_code == 200
    assert (resp.json()["estado"], resp.json()["monto"]) == ("pendiente", 80)
    db.expire_all()
    guardado = db.get(OffsetGanancia, creado["id"])
    assert (guardado.estado, guardado.monto) == ("pendiente", 80)


def test_a_description_edit_without_autoflush_keeps_it_approved(client, db, aprobador) -> None:
    creado = _crear(client, aprobador)
    client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)
    db.autoflush = False

    resp = client.put(f"{BASE}/{creado['id']}", json={"descripcion": "X"}, headers=aprobador)

    assert (resp.json()["estado"], resp.json()["descripcion"], resp.json()["monto"]) == ("activa", "X", 50)
    db.expire_all()
    assert (db.get(OffsetGanancia, creado["id"]).descripcion, db.get(OffsetGanancia, creado["id"]).estado) == (
        "X",
        "activa",
    )
