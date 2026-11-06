"""The cost mode change's API contract (`POST /api/sell-in/productos/{item_id}/modos/vista-previa` and `.../modos`):
every permission path (D7), the fields it takes and refuses (a field it does not take is a 422, never dropped), and a
lock error from another writer, which answers a 409 to retry instead of a raw 500."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.models.producto import ProductoERP, TipoMoneda
from app.services.sell_in import modos

BASE = "/api/sell-in/productos"
HOY = date.today()
AYER = HOY - timedelta(days=1)
PONDERADO, ULTIMO, MANUAL, RETRO = (
    "sell_in.costo_ponderado",
    "sell_in.costo_ultimo",
    "sell_in.costo_manual",
    "sell_in.costo_retroactivo",
)


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


def _cuerpo(modo, desde, **extra) -> dict:
    return {"modo": modo, "desde": desde.isoformat(), **extra}


CASOS = [
    ("ponderado", HOY, [], PONDERADO),
    ("ponderado", HOY, [ULTIMO, MANUAL, RETRO], PONDERADO),
    ("ultimo", HOY, [PONDERADO, MANUAL, RETRO], ULTIMO),
    ("ponderado", AYER, [PONDERADO], RETRO),
    ("ponderado", AYER, [RETRO], PONDERADO),
    ("ultimo", AYER, [ULTIMO], RETRO),
    ("fifo", HOY, [RETRO], f"{PONDERADO} | {ULTIMO} | {MANUAL}"),
    ("fifo", AYER, [ULTIMO], RETRO),
]


@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
@pytest.mark.parametrize(("modo", "desde", "tiene", "falta"), CASOS)
def test_forbidden_path_names_the_missing_one(
    client, rol_admin, lector, grant_permiso, producto, ruta, modo, desde, tiene, falta
) -> None:
    for p in tiene:
        grant_permiso(rol_admin, p)
    extra = {"huella": "0" * 64} if ruta == "modos" else {}
    resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo(modo, desde, **extra), headers=lector)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["message"] == f"Missing permission: {falta}"
    assert client.get(f"{BASE}/4512/modos", headers=lector).json()["historial"] == []


@pytest.mark.parametrize(
    ("modo", "desde", "tiene"),
    [
        ("ponderado", HOY, [PONDERADO]),
        ("ponderado", HOY + timedelta(days=30), [PONDERADO]),
        ("ultimo", HOY, [ULTIMO]),
        ("ponderado", AYER, [PONDERADO, RETRO]),
        ("ultimo", AYER, [ULTIMO, RETRO]),
        ("fifo", HOY, [PONDERADO]),
        ("fifo", HOY, [ULTIMO]),
        ("fifo", HOY, [MANUAL]),
        ("fifo", AYER, [MANUAL, RETRO]),
    ],
)
def test_allowed_paths_preview_then_save(
    client, rol_admin, lector, grant_permiso, producto, modo, desde, tiene
) -> None:
    for p in tiene:
        grant_permiso(rol_admin, p)
    vista = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo(modo, desde), headers=lector)
    assert vista.status_code == 200, vista.text
    resp = client.post(f"{BASE}/4512/modos", json=_cuerpo(modo, desde, huella=vista.json()["huella"]), headers=lector)
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_no_auth(client, producto, ruta) -> None:
    resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo("ponderado", HOY, huella="0" * 64))
    assert resp.status_code in (401, 403), resp.text


def test_mode_permission_without_sell_in_ver(client, rol_admin, admin_auth_headers, grant_permiso, producto) -> None:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, PONDERADO)
    resp = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=admin_auth_headers)
    assert resp.status_code == 403 and "sell_in.ver" in resp.text, resp.text


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"desde": HOY.isoformat()},
        {"modo": "ponderado"},
        {"modo": "ponderado", "desde": None},
        {"modo": "otro", "desde": HOY.isoformat()},
        {"modo": "PONDERADO", "desde": HOY.isoformat()},
        {"modo": "ponderado", "desde": "no-es-fecha"},
    ],
)
@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_omitted_or_bad_field_is_422(client, rol_admin, lector, grant_permiso, producto, cuerpo, ruta) -> None:
    grant_permiso(rol_admin, PONDERADO)
    grant_permiso(rol_admin, RETRO)
    extra = {"huella": "0" * 64} if ruta == "modos" else {}
    assert client.post(f"{BASE}/4512/{ruta}", json={**cuerpo, **extra}, headers=lector).status_code == 422


def test_confirm_without_or_with_junk_fingerprint_saves_nothing(
    client, rol_admin, lector, grant_permiso, producto
) -> None:
    grant_permiso(rol_admin, PONDERADO)
    assert client.post(f"{BASE}/4512/modos", json=_cuerpo("ponderado", HOY), headers=lector).status_code == 422
    assert (
        client.post(f"{BASE}/4512/modos", json=_cuerpo("ponderado", HOY, huella="x"), headers=lector).status_code == 422
    )
    assert (
        client.post(f"{BASE}/4512/modos", json=_cuerpo("ponderado", HOY, huella="0" * 64), headers=lector).status_code
        == 409
    )
    assert client.get(f"{BASE}/4512/modos", headers=lector).json()["historial"] == []


@pytest.mark.parametrize("extra", [{"cantidad": 5}, {"costo_unit": "12.50"}, {"origen": "carga"}, {"usuario_id": 1}])
@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_unknown_fields_are_rejected(client, rol_admin, lector, grant_permiso, producto, extra, ruta) -> None:
    grant_permiso(rol_admin, PONDERADO)
    huella = {}
    if ruta == "modos":
        vista = client.post(f"{BASE}/4512/modos/vista-previa", json=_cuerpo("ponderado", HOY), headers=lector)
        huella = {"huella": vista.json()["huella"]}
    resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo("ponderado", HOY, **huella, **extra), headers=lector)
    assert resp.status_code == 422, (resp.status_code, resp.text)


@pytest.mark.parametrize("pgcode", ["40P01", "55P03", "57014"])
@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_a_lock_error_answers_a_409_to_retry(
    client, rol_admin, lector, grant_permiso, producto, monkeypatch, pgcode, ruta
) -> None:
    grant_permiso(rol_admin, PONDERADO)

    class Orig(Exception):
        pass

    Orig.pgcode = pgcode

    def choca(*a, **k):
        raise OperationalError("SELECT", {}, Orig("deadlock detected"))

    monkeypatch.setattr(modos, "vista_previa" if ruta != "modos" else "confirmar", choca)
    extra = {"huella": "0" * 64} if ruta == "modos" else {}
    try:
        resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo("ponderado", HOY, **extra), headers=lector)
    except OperationalError:
        pytest.fail("OperationalError reached the ASGI server: raw 500")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["message"] == (
        "Another operation is changing the product right now: try again in a few seconds"
    )


@pytest.mark.parametrize("pgcode", ["23505", None])
@pytest.mark.parametrize("ruta", ["modos/vista-previa", "modos"])
def test_any_other_database_error_is_not_a_retry(
    client, rol_admin, lector, grant_permiso, producto, monkeypatch, pgcode, ruta
) -> None:
    grant_permiso(rol_admin, PONDERADO)

    class Orig(Exception):
        pass

    if pgcode is not None:
        Orig.pgcode = pgcode

    def choca(*a, **k):
        raise OperationalError("SELECT", {}, Orig("something else"))

    monkeypatch.setattr(modos, "vista_previa" if ruta != "modos" else "confirmar", choca)
    extra = {"huella": "0" * 64} if ruta == "modos" else {}
    resp = client.post(f"{BASE}/4512/{ruta}", json=_cuerpo("ponderado", HOY, **extra), headers=lector)
    assert resp.status_code == 500, resp.text
