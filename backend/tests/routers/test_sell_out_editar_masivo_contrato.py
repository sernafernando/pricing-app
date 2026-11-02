"""Bulk edit HTTP contract (verifier probes of PR #2014, kept as regression tests; SQLite like the router test)."""

from __future__ import annotations

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo

BASE = "/api/sell-out/campanas"
EDITAR = f"{BASE}/editar-masivo"


@pytest.fixture()
def grupos(db):
    rows = [OffsetGrupo(nombre="G")]
    db.add_all(rows)
    db.flush()
    return [r.id for r in rows]


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


def _crear(client, h, grupos, **o) -> int:
    body = {
        "nombre": "R",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto_unit": "10",
        "moneda": "ARS",
        "grupo_ids": grupos,
        **o,
    }
    r = client.post(BASE, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize(
    "extra",
    [
        {"monto_unit": "99"},
        {"nombre": "Otro"},
        {"grupo_ids": []},
        {"descripcion": "x"},
        {"tope_unidades": 5},
        {"estado": "anulada"},
        {"fecha_hsata": "2027-01-01"},
    ],
)
def test_a_field_outside_the_three_is_refused_not_silently_dropped(client, gestor, grupos, extra) -> None:
    cid = _crear(client, gestor, grupos)
    r = client.post(EDITAR, json={"campana_ids": [cid], "acumulable": False, **extra}, headers=gestor)
    fila = client.get(f"{BASE}/{cid}", headers=gestor).json()
    print("EXTRA", extra, r.status_code, fila["monto_unit"], fila["nombre"], fila["acumulable"])
    assert r.status_code == 422, r.text


def test_only_an_unknown_field_is_a_422(client, gestor, grupos) -> None:
    cid = _crear(client, gestor, grupos)
    r = client.post(EDITAR, json={"campana_ids": [cid], "monto_unit": "99"}, headers=gestor)
    assert r.status_code == 422


def test_cap_counts_distinct_and_exactly_500_passes_the_cap(client, gestor, grupos) -> None:
    cid = _crear(client, gestor, grupos)
    r = client.post(EDITAR, json={"campana_ids": list(range(1, 502)), "acumulable": False}, headers=gestor)
    assert r.status_code == 422
    r = client.post(EDITAR, json={"campana_ids": [cid] * 600, "acumulable": False}, headers=gestor)
    assert r.status_code == 200 and r.json() == {"editadas": [cid], "sin_cambio": []}
    assert client.get(f"{BASE}/{cid}", headers=gestor).json()["acumulable"] is False


def test_no_auth_is_refused(client) -> None:
    assert client.post(EDITAR, json={"campana_ids": [1], "acumulable": False}).status_code in (401, 403)


def test_false_is_a_filled_value(client, gestor, grupos, db) -> None:
    cid = _crear(client, gestor, grupos)
    r = client.post(EDITAR, json={"campana_ids": [cid], "acumulable": False}, headers=gestor)
    assert r.json()["editadas"] == [cid]
    t = TipoAccion.SELL_OUT_CAMPANA_EDITADA
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == t).count() == 1
