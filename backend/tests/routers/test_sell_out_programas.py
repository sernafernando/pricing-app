"""Sell-out programs API (`/api/sell-out/programas`), campaign system S1.

Runs on the SQLite test database like the campaigns router tests; the assignment, the suggestions and the list
counts are also proven on Postgres by `tests/services/sell_out/test_programas_postgres.py`.
"""

from __future__ import annotations

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import SellOutCampana, SellOutDirty, SellOutPrograma

BASE = "/api/sell-out/programas"
CAMPANAS = "/api/sell-out/campanas"
VER = "sell_out.ver"
GESTIONAR = "sell_out.gestionar"


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture()
def grupo(db) -> int:
    row = OffsetGrupo(nombre="Epson tintas")
    db.add(row)
    db.flush()
    return row.id


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    grant_permiso(rol_admin, GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    return admin_auth_headers


def _campana(client, headers, grupo: int, nombre: str = "EPSON PROG 24", **overrides) -> dict:
    body = {
        "nombre": nombre,
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto_unit": "1500.00",
        "grupo_ids": [grupo],
        **overrides,
    }
    resp = client.post(CAMPANAS, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _programa(client, headers, nombre: str = "EPSON PROG", **extra) -> dict:
    resp = client.post(BASE, json={"nombre": nombre, **extra}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _asignar(client, headers, campana_ids: list[int], programa_id):
    return client.post(
        f"{BASE}/asignar", json={"campana_ids": campana_ids, "programa_id": programa_id}, headers=headers
    )


# ── Permissions ─────────────────────────────────────────────────────

ESCRITURAS = [("post", BASE), ("patch", f"{BASE}/1"), ("post", f"{BASE}/asignar")]
LECTURAS = [("get", BASE), ("get", f"{BASE}/sugerencias")]
_BODY = {"nombre": "EPSON PROG", "campana_ids": [1], "programa_id": None}


@pytest.mark.parametrize("method,url", ESCRITURAS + LECTURAS)
def test_every_endpoint_requires_a_permission(client, auth_headers, method, url) -> None:
    kwargs = {"headers": auth_headers}
    if method != "get":
        kwargs["json"] = _BODY
    assert getattr(client, method)(url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,url", ESCRITURAS)
def test_reading_does_not_allow_writing(client, lector, method, url) -> None:
    resp = getattr(client, method)(url, json=_BODY, headers=lector)
    assert resp.status_code == 403
    assert GESTIONAR in _message(resp)


@pytest.mark.parametrize("method,url", ESCRITURAS + LECTURAS)
def test_every_endpoint_requires_authentication(client, method, url) -> None:
    resp = getattr(client, method)(url, json=_BODY) if method != "get" else client.get(url)
    assert resp.status_code in (401, 403)


# ── Create, edit, list ──────────────────────────────────────────────


def test_create_trims_the_name_and_starts_active_and_empty(client, gestor, db, admin_user) -> None:
    out = _programa(client, gestor, "  EPSON PROG  ", descripcion="Programa de sell out de Epson")
    assert out == {
        "id": out["id"],
        "nombre": "EPSON PROG",
        "descripcion": "Programa de sell out de Epson",
        "estado": "activo",
        "campanas": 0,
        "activas": 0,
        "desde": None,
        "hasta": None,
    }
    assert db.get(SellOutPrograma, out["id"]).usuario_id == admin_user.id


@pytest.mark.parametrize("nombre", ["", "   "])
def test_create_refuses_an_empty_name(client, gestor, nombre) -> None:
    assert client.post(BASE, json={"nombre": nombre}, headers=gestor).status_code == 422


def test_a_name_taken_ignoring_case_is_a_409_naming_it(client, gestor) -> None:
    _programa(client, gestor, "EPSON PROG")
    resp = client.post(BASE, json={"nombre": "epson prog"}, headers=gestor)
    assert resp.status_code == 409
    assert _message(resp) == "Ya existe un programa llamado «EPSON PROG»."


def test_patch_changes_only_the_fields_sent(client, gestor) -> None:
    programa = _programa(client, gestor, "EPSON PROG", descripcion="Epson")
    resp = client.patch(f"{BASE}/{programa['id']}", json={"estado": "archivado"}, headers=gestor)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["nombre"], resp.json()["descripcion"], resp.json()["estado"]) == (
        "EPSON PROG",
        "Epson",
        "archivado",
    )
    resp = client.patch(
        f"{BASE}/{programa['id']}", json={"nombre": " Epson Prog ", "descripcion": None}, headers=gestor
    )
    assert (resp.json()["nombre"], resp.json()["descripcion"], resp.json()["estado"]) == (
        "Epson Prog",  # its own name in another case is not a duplicate
        None,
        "archivado",
    )


def test_patch_unknown_is_404_duplicate_409_and_null_name_422(client, gestor) -> None:
    epson = _programa(client, gestor, "EPSON PROG")
    rebate = _programa(client, gestor, "Rebate")
    assert client.patch(f"{BASE}/99999", json={"nombre": "X"}, headers=gestor).status_code == 404
    resp = client.patch(f"{BASE}/{rebate['id']}", json={"nombre": "Epson prog"}, headers=gestor)
    assert resp.status_code == 409
    assert "«EPSON PROG»" in _message(resp)
    assert client.patch(f"{BASE}/{epson['id']}", json={"nombre": None}, headers=gestor).status_code == 422
    assert client.patch(f"{BASE}/{epson['id']}", json={"estado": "borrado"}, headers=gestor).status_code == 422


def test_list_sorts_by_name_counts_campaigns_and_filters_by_state(client, gestor, grupo) -> None:
    rebate = _programa(client, gestor, "Rebate")
    epson = _programa(client, gestor, "EPSON PROG")
    vieja = _campana(client, gestor, grupo, "EPSON PROG 24", fecha_desde="2026-01-01", fecha_hasta="2026-03-31")
    nueva = _campana(client, gestor, grupo, "EPSON PROG 25", fecha_desde="2026-04-01", fecha_hasta="2026-06-30")
    assert client.post(f"{CAMPANAS}/{vieja['id']}/anular", headers=gestor).status_code == 200
    assert _asignar(client, gestor, [vieja["id"], nueva["id"]], epson["id"]).status_code == 200
    client.patch(f"{BASE}/{rebate['id']}", json={"estado": "archivado"}, headers=gestor)

    filas = client.get(BASE, headers=gestor).json()
    assert [(f["nombre"], f["campanas"], f["activas"], f["desde"], f["hasta"]) for f in filas] == [
        ("EPSON PROG", 2, 1, "2026-01-01", "2026-06-30"),
        ("Rebate", 0, 0, None, None),
    ]
    archivados = client.get(BASE, params={"estado": "archivado"}, headers=gestor).json()
    assert [f["nombre"] for f in archivados] == ["Rebate"]


# ── Assignment ──────────────────────────────────────────────────────


def test_assign_sets_the_program_audits_each_campaign_and_queues_nothing(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "EPSON PROG")
    a = _campana(client, gestor, grupo, "EPSON PROG 24")
    b = _campana(client, gestor, grupo, "EPSON PROG 25")
    db.query(SellOutDirty).delete()
    db.flush()

    resp = _asignar(client, gestor, [a["id"], b["id"], a["id"]], programa["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"asignadas": 2, "sin_cambio": 0}
    assert db.query(SellOutDirty).count() == 0
    filas = (
        db.query(Auditoria)
        .filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA)
        .order_by(Auditoria.id)
        .all()
    )
    assert [(f.valores_anteriores, f.valores_nuevos, f.es_masivo, f.item_id) for f in filas] == [
        (
            {"campana_id": c["id"], "programa_id": None, "programa": None},
            {"campana_id": c["id"], "programa_id": programa["id"], "programa": "EPSON PROG"},
            True,
            None,
        )
        for c in (a, b)
    ]
    detalle = client.get(f"{CAMPANAS}/{a['id']}", headers=gestor).json()
    assert (detalle["programa_id"], detalle["programa"]) == (
        programa["id"],
        {"id": programa["id"], "nombre": "EPSON PROG"},
    )

    # Again: nothing changes, nothing is audited.
    assert _asignar(client, gestor, [a["id"], b["id"]], programa["id"]).json() == {"asignadas": 0, "sin_cambio": 2}
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA).count() == 2


def test_one_campaign_moved_between_programs_and_cleared_is_not_bulk(client, gestor, grupo, db) -> None:
    epson = _programa(client, gestor, "EPSON PROG")
    rebate = _programa(client, gestor, "Rebate")
    c = _campana(client, gestor, grupo, "Rebate Q4 2024")
    _asignar(client, gestor, [c["id"]], epson["id"])
    assert _asignar(client, gestor, [c["id"]], rebate["id"]).json() == {"asignadas": 1, "sin_cambio": 0}
    assert _asignar(client, gestor, [c["id"]], None).json() == {"asignadas": 1, "sin_cambio": 0}
    assert db.get(SellOutCampana, c["id"]).programa_id is None
    filas = (
        db.query(Auditoria)
        .filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA)
        .order_by(Auditoria.id)
        .all()
    )
    assert [(f.valores_anteriores["programa"], f.valores_nuevos["programa"], f.es_masivo) for f in filas] == [
        (None, "EPSON PROG", False),
        ("EPSON PROG", "Rebate", False),
        ("Rebate", None, False),
    ]


def test_assign_works_on_a_voided_campaign_and_keeps_its_money(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "EPSON PROG")
    c = _campana(client, gestor, grupo, "EPSON PROG 24", monto_unit="25.50")
    assert client.post(f"{CAMPANAS}/{c['id']}/anular", headers=gestor).status_code == 200
    assert _asignar(client, gestor, [c["id"]], programa["id"]).json() == {"asignadas": 1, "sin_cambio": 0}
    campana = db.get(SellOutCampana, c["id"])
    assert (campana.estado, float(campana.monto_unit), campana.programa_id) == ("anulada", 25.5, programa["id"])


def test_assign_is_all_or_nothing_and_names_the_unknown_campaigns(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "EPSON PROG")
    c = _campana(client, gestor, grupo)
    resp = _asignar(client, gestor, [c["id"], 99998, 99999], programa["id"])
    assert resp.status_code == 422
    assert _message(resp) == "Las campañas 99998, 99999 no existen."
    assert db.get(SellOutCampana, c["id"]).programa_id is None
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA).count() == 0


def test_assign_to_an_unknown_program_is_404_and_to_an_archived_one_422(client, gestor, grupo, db) -> None:
    c = _campana(client, gestor, grupo)
    assert _asignar(client, gestor, [c["id"]], 99999).status_code == 404
    programa = _programa(client, gestor, "Rebate")
    client.patch(f"{BASE}/{programa['id']}", json={"estado": "archivado"}, headers=gestor)
    resp = _asignar(client, gestor, [c["id"]], programa["id"])
    assert resp.status_code == 422
    assert _message(resp) == "El programa «Rebate» está archivado."
    assert db.get(SellOutCampana, c["id"]).programa_id is None


@pytest.mark.parametrize(
    "body",
    [
        {"campana_ids": [], "programa_id": None},
        {"campana_ids": list(range(1, 502)), "programa_id": None},
        {"campana_ids": [1]},
    ],
)
def test_assign_refuses_an_empty_or_too_large_selection_or_a_missing_program(client, gestor, body) -> None:
    assert client.post(f"{BASE}/asignar", json=body, headers=gestor).status_code == 422


# ── Suggestions ─────────────────────────────────────────────────────


def test_suggestions_group_campaigns_without_a_program_by_base_name(client, gestor, grupo) -> None:
    epson = [
        _campana(client, gestor, grupo, nombre, fecha_desde=desde, fecha_hasta=hasta)
        for nombre, desde, hasta in (
            ("EPSON PROG 25", "2026-04-01", "2026-06-30"),
            ("EPSON PROG 24", "2026-01-01", "2026-03-31"),
            ("epson prog 26", "2026-07-01", "2026-09-30"),
        )
    ]
    rebate = [_campana(client, gestor, grupo, n) for n in ("Rebate Q4 2024", "Rebate Q1 2025")]
    _campana(client, gestor, grupo, "TP-Link 2% noviembre")  # alone: no group
    asignada = _campana(client, gestor, grupo, "Rebate Q2 2025")
    programa = _programa(client, gestor, "Rebate")
    _asignar(client, gestor, [asignada["id"]], programa["id"])

    resp = client.get(f"{BASE}/sugerencias", headers=gestor)
    assert resp.status_code == 200, resp.text
    assert [(g["base"], [c["id"] for c in g["campanas"]]) for g in resp.json()] == [
        ("EPSON PROG", [epson[1]["id"], epson[0]["id"], epson[2]["id"]]),  # by start date
        ("Rebate", [rebate[0]["id"], rebate[1]["id"]]),
    ]
    assert resp.json()[0]["campanas"][0] == {
        "id": epson[1]["id"],
        "nombre": "EPSON PROG 24",
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-03-31",
        "estado": "activa",
    }
