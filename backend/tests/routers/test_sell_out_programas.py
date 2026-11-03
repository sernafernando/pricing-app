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
    row = OffsetGrupo(nombre="Marca tintas")
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


def _campana(client, headers, grupo: int, nombre: str = "MARCA PROG 24", **overrides) -> dict:
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


def _programa(client, headers, nombre: str = "MARCA PROG", **extra) -> dict:
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
_BODY = {"nombre": "MARCA PROG", "campana_ids": [1], "programa_id": None}


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
    out = _programa(client, gestor, "  MARCA PROG  ", descripcion="Programa de sell out de Marca")
    assert out == {
        "id": out["id"],
        "nombre": "MARCA PROG",
        "descripcion": "Programa de sell out de Marca",
        "estado": "activo",
        "campanas": 0,
        "activas": 0,
        "desde": None,
        "hasta": None,
        "nombres": 0,
    }
    assert db.get(SellOutPrograma, out["id"]).usuario_id == admin_user.id


@pytest.mark.parametrize("nombre", ["", "   "])
def test_create_refuses_an_empty_name(client, gestor, nombre) -> None:
    assert client.post(BASE, json={"nombre": nombre}, headers=gestor).status_code == 422


def test_a_name_taken_ignoring_case_is_a_409_naming_it(client, gestor) -> None:
    _programa(client, gestor, "MARCA PROG")
    resp = client.post(BASE, json={"nombre": "marca prog"}, headers=gestor)
    assert resp.status_code == 409
    assert _message(resp) == "Ya existe un programa llamado «MARCA PROG»."


def test_patch_changes_only_the_fields_sent(client, gestor) -> None:
    programa = _programa(client, gestor, "MARCA PROG", descripcion="Marca")
    resp = client.patch(f"{BASE}/{programa['id']}", json={"estado": "archivado"}, headers=gestor)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["nombre"], resp.json()["descripcion"], resp.json()["estado"]) == (
        "MARCA PROG",
        "Marca",
        "archivado",
    )
    resp = client.patch(
        f"{BASE}/{programa['id']}", json={"nombre": " Marca Prog ", "descripcion": None}, headers=gestor
    )
    assert (resp.json()["nombre"], resp.json()["descripcion"], resp.json()["estado"]) == (
        "Marca Prog",  # its own name in another case is not a duplicate
        None,
        "archivado",
    )


def test_the_name_length_counts_after_trimming(client, gestor) -> None:
    justo = "N" * 200
    assert client.post(BASE, json={"nombre": f"  {justo}  "}, headers=gestor).status_code == 201
    assert client.post(BASE, json={"nombre": "N" * 201}, headers=gestor).status_code == 422


def test_an_empty_patch_changes_nothing(client, gestor) -> None:
    programa = _programa(client, gestor, "Programa sin cambios")

    resp = client.patch(f"{BASE}/{programa['id']}", json={}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == programa


def test_patch_unknown_is_404_duplicate_409_and_null_name_422(client, gestor) -> None:
    marca = _programa(client, gestor, "MARCA PROG")
    rebate = _programa(client, gestor, "Rebate")
    assert client.patch(f"{BASE}/99999", json={"nombre": "X"}, headers=gestor).status_code == 404
    resp = client.patch(f"{BASE}/{rebate['id']}", json={"nombre": "Marca prog"}, headers=gestor)
    assert resp.status_code == 409
    assert "«MARCA PROG»" in _message(resp)
    assert client.patch(f"{BASE}/{marca['id']}", json={"nombre": None}, headers=gestor).status_code == 422
    assert client.patch(f"{BASE}/{marca['id']}", json={"estado": "borrado"}, headers=gestor).status_code == 422


def test_list_sorts_by_name_counts_campaigns_and_filters_by_state(client, gestor, grupo) -> None:
    rebate = _programa(client, gestor, "Rebate")
    marca = _programa(client, gestor, "MARCA PROG")
    vieja = _campana(client, gestor, grupo, "MARCA PROG 24", fecha_desde="2026-01-01", fecha_hasta="2026-03-31")
    nueva = _campana(client, gestor, grupo, "MARCA PROG 25", fecha_desde="2026-04-01", fecha_hasta="2026-06-30")
    assert client.post(f"{CAMPANAS}/{vieja['id']}/anular", headers=gestor).status_code == 200
    assert _asignar(client, gestor, [vieja["id"], nueva["id"]], marca["id"]).status_code == 200
    client.patch(f"{BASE}/{rebate['id']}", json={"estado": "archivado"}, headers=gestor)

    filas = client.get(BASE, headers=gestor).json()["items"]
    assert [(f["nombre"], f["campanas"], f["activas"], f["desde"], f["hasta"]) for f in filas] == [
        ("MARCA PROG", 2, 1, "2026-01-01", "2026-06-30"),
        ("Rebate", 0, 0, None, None),
    ]
    archivados = client.get(BASE, params={"estado": "archivado"}, headers=gestor).json()["items"]
    assert [f["nombre"] for f in archivados] == ["Rebate"]


def test_list_counts_each_program_distinct_names_ignoring_case_and_spaces(client, gestor, grupo) -> None:
    """Slice E: `nombres` is how many distinct campaign names a program holds, ignoring case and repeated spaces,
    voided campaigns included (the group row's «N campañas · M nombres»)."""
    marca = _programa(client, gestor, "MARCA PROG")
    _programa(client, gestor, "Vacío")
    ids = [
        _campana(client, gestor, grupo, "MARCA PROG 3.0")["id"],
        _campana(client, gestor, grupo, "marca  prog 3.0")["id"],
        _campana(client, gestor, grupo, "MARCA PROGRAM1")["id"],
    ]
    assert client.post(f"{CAMPANAS}/{ids[2]}/anular", headers=gestor).status_code == 200
    assert _asignar(client, gestor, ids, marca["id"]).status_code == 200

    filas = client.get(BASE, headers=gestor).json()["items"]
    assert [(f["nombre"], f["campanas"], f["nombres"]) for f in filas] == [("MARCA PROG", 3, 2), ("Vacío", 0, 0)]
    assert client.patch(f"{BASE}/{marca['id']}", json={}, headers=gestor).json()["nombres"] == 2


# ── Assignment ──────────────────────────────────────────────────────


def test_assign_sets_the_program_audits_each_campaign_and_queues_nothing(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "MARCA PROG")
    a = _campana(client, gestor, grupo, "MARCA PROG 24")
    b = _campana(client, gestor, grupo, "MARCA PROG 25")
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
            {"campana_id": c["id"], "programa_id": programa["id"], "programa": "MARCA PROG"},
            True,
            None,
        )
        for c in (a, b)
    ]
    detalle = client.get(f"{CAMPANAS}/{a['id']}", headers=gestor).json()
    assert (detalle["programa_id"], detalle["programa"]) == (
        programa["id"],
        {"id": programa["id"], "nombre": "MARCA PROG"},
    )

    # Again: nothing changes, nothing is audited.
    assert _asignar(client, gestor, [a["id"], b["id"]], programa["id"]).json() == {"asignadas": 0, "sin_cambio": 2}
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA).count() == 2


def test_one_campaign_moved_between_programs_and_cleared_is_not_bulk(client, gestor, grupo, db) -> None:
    marca = _programa(client, gestor, "MARCA PROG")
    rebate = _programa(client, gestor, "Rebate")
    c = _campana(client, gestor, grupo, "Rebate Q4 2024")
    _asignar(client, gestor, [c["id"]], marca["id"])
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
        (None, "MARCA PROG", False),
        ("MARCA PROG", "Rebate", False),
        ("Rebate", None, False),
    ]


def test_assign_works_on_a_voided_campaign_and_keeps_its_money(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "MARCA PROG")
    c = _campana(client, gestor, grupo, "MARCA PROG 24", monto_unit="25.50")
    assert client.post(f"{CAMPANAS}/{c['id']}/anular", headers=gestor).status_code == 200
    assert _asignar(client, gestor, [c["id"]], programa["id"]).json() == {"asignadas": 1, "sin_cambio": 0}
    campana = db.get(SellOutCampana, c["id"])
    assert (campana.estado, float(campana.monto_unit), campana.programa_id) == ("anulada", 25.5, programa["id"])


def test_assign_is_all_or_nothing_and_names_the_unknown_campaigns(client, gestor, grupo, db) -> None:
    programa = _programa(client, gestor, "MARCA PROG")
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


def test_suggestions_group_campaigns_without_a_program_by_identical_dates(client, gestor, grupo) -> None:
    def marca(nombre: str) -> dict:
        return _campana(client, gestor, grupo, nombre, fecha_desde="2026-08-01", fecha_hasta="2026-12-31")

    e = [marca("MARCA PROG 3.0"), marca("MARCA PROGRAM1"), marca("MARCA PROGRAM1")]
    asignada = marca("MARCA PROGR 7.5")
    _campana(client, gestor, grupo, "MODELO 8180", fecha_desde="2026-01-01", fecha_hasta="2026-12-31")  # alone
    _asignar(client, gestor, [asignada["id"]], _programa(client, gestor, "MARCA PROG")["id"])

    resp = client.get(f"{BASE}/sugerencias", headers=gestor)
    assert resp.status_code == 200, resp.text
    grupos = resp.json()["items"]
    assert [(g["base"], g["fecha_desde"], g["fecha_hasta"], g["nombres"]) for g in grupos] == [
        ("MARCA", "2026-08-01", "2026-12-31", 2)
    ]
    assert [c["id"] for c in grupos[0]["campanas"]] == [e[0]["id"], e[1]["id"], e[2]["id"]]
    assert grupos[0]["campanas"][0] == {
        "id": e[0]["id"],
        "nombre": "MARCA PROG 3.0",
        "fecha_desde": "2026-08-01",
        "fecha_hasta": "2026-12-31",
        "estado": "activa",
    }


def test_both_lists_are_paginated_like_the_campaigns(client, gestor, grupo) -> None:
    for nombre in ("A programa", "B programa", "C programa"):
        _programa(client, gestor, nombre)
    for nombre in ("MARCA PROG 3.0", "MARCA PROGRAM1"):
        _campana(client, gestor, grupo, nombre, fecha_desde="2026-08-01", fecha_hasta="2026-12-31")
    for nombre in ("M20 / M80 SP", "M30/M70"):
        _campana(client, gestor, grupo, nombre, fecha_desde="2025-11-01", fecha_hasta="2026-12-31")

    pagina = client.get(BASE, params={"page": 2, "page_size": 2}, headers=gestor).json()
    assert [f["nombre"] for f in pagina["items"]] == ["C programa"]
    assert (pagina["total"], pagina["page"], pagina["page_size"]) == (3, 2, 2)

    sugeridas = client.get(f"{BASE}/sugerencias", params={"page_size": 1}, headers=gestor).json()
    # Two groups of 2: the earlier dates first.
    assert [g["base"] for g in sugeridas["items"]] == ["Del 01/11/2025 al 31/12/2026"]
    assert (sugeridas["total"], sugeridas["page"], sugeridas["page_size"]) == (2, 1, 1)
    assert client.get(BASE, params={"page_size": 201}, headers=gestor).status_code == 422
