"""Bulk edit of sell-out campaigns over HTTP (`POST /api/sell-out/campanas/editar-masivo`), M1.

SQLite, like `test_sell_out_campanas.py`: permissions, the request caps, the error shapes and the response
shapes. The rules are proven on Postgres by
`tests/services/sell_out/test_editar_masivo_postgres.py`.
"""

from __future__ import annotations

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo

BASE = "/api/sell-out/campanas"
EDITAR = f"{BASE}/editar-masivo"
VER = "sell_out.ver"
GESTIONAR = "sell_out.gestionar"
EDITADA = TipoAccion.SELL_OUT_CAMPANA_EDITADA
REINTENTAR = "Reintentar en unos segundos."


@pytest.fixture()
def grupos(db):
    rows = [OffsetGrupo(nombre="MARCA PROG 3.0")]
    db.add_all(rows)
    db.flush()
    return [row.id for row in rows]


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    grant_permiso(rol_admin, GESTIONAR)
    return admin_auth_headers


def _message(resp) -> str:
    return resp.json()["error"]["message"]


def _crear(client, headers, grupos, **overrides) -> int:
    body = {
        "nombre": "Rebate Q4 2026",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto_unit": "10",
        "moneda": "ARS",
        "grupo_ids": grupos,
        **overrides,
    }
    resp = client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _campana(client, headers, cid: int) -> dict:
    return client.get(f"{BASE}/{cid}", headers=headers).json()


@pytest.mark.parametrize("url", [EDITAR])
def test_both_endpoints_need_sell_out_gestionar(client, auth_headers, rol_ventas, grant_permiso, url) -> None:
    grant_permiso(rol_ventas, VER)
    resp = client.post(url, json={"campana_ids": [1], "acumulable": False}, headers=auth_headers)
    assert resp.status_code == 403
    assert GESTIONAR in _message(resp)


@pytest.mark.parametrize("url", [EDITAR])
def test_a_brand_scoped_pm_cannot_bulk_edit(client, gestor, grupos, auth_headers, rol_ventas, grant_permiso, url):
    """Like the bulk void: a PM with `sell_out.repartir` only splits shares; `gestionar` is the per-record check."""
    cid = _crear(client, gestor, grupos)
    grant_permiso(rol_ventas, VER)
    grant_permiso(rol_ventas, "sell_out.repartir")

    resp = client.post(url, json={"campana_ids": [cid], "fecha_hasta": "2026-12-31"}, headers=auth_headers)

    assert resp.status_code == 403
    assert _campana(client, gestor, cid)["fecha_hasta"] == "2026-11-30"


@pytest.mark.parametrize("url", [EDITAR])
@pytest.mark.parametrize(
    "body,mensaje",
    [
        ({"campana_ids": [], "acumulable": False}, "Elegí al menos una campaña para editar."),
        (
            {"campana_ids": list(range(1, 502)), "acumulable": False},
            "Se pueden editar hasta 500 campañas por vez.",
        ),
        (
            {"campana_ids": [1], "fecha_desde": None},
            "Completá al menos un campo para editar: fecha desde, fecha hasta o acumulable.",
        ),
    ],
)
def test_an_empty_or_too_large_selection_or_no_field_is_a_422(client, gestor, url, body, mensaje) -> None:
    resp = client.post(url, json=body, headers=gestor)
    assert resp.status_code == 422, resp.text
    assert _message(resp) == mensaje


def test_the_apply_returns_the_edited_and_the_unchanged(client, gestor, grupos, db) -> None:
    a = _crear(client, gestor, grupos)
    igual = _crear(client, gestor, grupos, fecha_hasta="2026-12-31")

    resp = client.post(EDITAR, json={"campana_ids": [igual, a], "fecha_hasta": "2026-12-31"}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"editadas": [a], "sin_cambio": [igual]}
    assert _campana(client, gestor, a)["fecha_hasta"] == "2026-12-31"
    [audit] = db.query(Auditoria).filter(Auditoria.tipo_accion == EDITADA).all()
    assert (audit.valores_nuevos["campana_id"], audit.es_masivo) == (a, True)


def test_unknown_or_refused_rows_are_a_422_naming_each_one_and_nothing_changes(client, gestor, grupos, db) -> None:
    a = _crear(client, gestor, grupos)
    invertida = _crear(client, gestor, grupos, nombre="MODELO 8180", fecha_desde="2026-12-01", fecha_hasta="2026-12-31")

    resp = client.post(
        EDITAR, json={"campana_ids": [a, 999999, invertida], "fecha_hasta": "2026-11-15"}, headers=gestor
    )

    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "EDICION_RECHAZADA"
    assert error["message"] == "No se editó ninguna campaña: 2 no se pueden editar."
    assert error["rechazadas"] == [
        {
            "id": invertida,
            "nombre": "MODELO 8180",
            "motivo": "La campaña MODELO 8180 quedaría con la fecha hasta (15/11/2026) antes que la fecha desde "
            "(01/12/2026)",
        },
        {"id": 999999, "nombre": None, "motivo": "La campaña 999999 no existe"},
    ]
    assert _campana(client, gestor, a)["fecha_hasta"] == "2026-11-30"
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == EDITADA).count() == 0


@pytest.mark.parametrize("url", [EDITAR])
def test_a_campaign_being_rebuilt_is_a_409_with_the_retry_message(client, gestor, grupos, monkeypatch, url) -> None:
    from app.services.sell_out import campanas as service

    a = _crear(client, gestor, grupos, nombre="MARCA PROG 3.0")

    def _recalculando(db, campana_ids):
        db.rollback()
        raise service.SellOutRecalculando("La campaña se está recalculando. Reintentar en unos segundos.")

    monkeypatch.setattr(service, "_encolar", _recalculando)

    resp = client.post(url, json={"campana_ids": [a, 999999], "fecha_hasta": "2026-12-31"}, headers=gestor)

    assert resp.status_code == 409, resp.text
    assert _message(resp) == (
        f"No se editó ninguna campaña: la campaña {a} (MARCA PROG 3.0) se está recalculando. {REINTENTAR}"
    )
    assert resp.json()["error"]["rechazadas"] == [
        {"id": a, "nombre": "MARCA PROG 3.0", "motivo": f"Se está recalculando. {REINTENTAR}"},
        {"id": 999999, "nombre": None, "motivo": "La campaña 999999 no existe"},
    ]
    assert _campana(client, gestor, a)["fecha_hasta"] == "2026-11-30"


def test_a_deadlock_is_a_409_with_the_retry_message(client, gestor, grupos, monkeypatch) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.services.sell_out import campanas as service

    a = _crear(client, gestor, grupos)

    class _Deadlock(Exception):
        pgcode = "40P01"

    def _en_deadlock(db, campana_ids):
        raise DBAPIError("UPDATE sell_out_dirty ...", {}, _Deadlock())

    monkeypatch.setattr(service, "_encolar", _en_deadlock)

    resp = client.post(EDITAR, json={"campana_ids": [a], "acumulable": False}, headers=gestor)

    assert resp.status_code == 409, resp.text
    assert _message(resp) == (
        f"No se editó ninguna campaña: otra operación está modificando la campaña {a} en este momento. {REINTENTAR}"
    )
    assert _campana(client, gestor, a)["acumulable"] is True
