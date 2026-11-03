"""
RMA "Para borrar" view (owner, 2026-11-03): "necesito una vista sencilla de rma donde se vean los pedidos que se
marcan parar borrar ... y que tenga un tilde cuando ya se revisó para que no aparezca más" ... "(con un filtro claro)".

- GET /rma-seguimiento/para-borrar lists the active cases with `marcado_borrar_pedido`, filtered by
  pendientes (default) / revisados / todos, with the count of each.
- PUT /rma-seguimiento/{id}/borrar-revisado ticks or unticks "Revisado": it stores who and when, or clears both.
- Viewing needs rma.ver (like the RMA list); the tick needs rma.gestionar.
"""

from contextlib import contextmanager
from datetime import datetime, UTC
from unittest.mock import patch

import pytest

from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial


@contextmanager
def _permisos(*granted: str):
    with patch(
        "app.services.permisos_service.PermisosService.tiene_permiso",
        side_effect=lambda _user, permiso: permiso in granted,
    ):
        yield


@pytest.fixture()
def casos(db, active_user) -> dict[str, RmaCaso]:
    reviewed_at = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
    rows = {
        "pendiente": RmaCaso(numero_caso="RMA-2026-9101", estado="abierto", marcado_borrar_pedido=True),
        "revisado": RmaCaso(
            numero_caso="RMA-2026-9102",
            estado="abierto",
            marcado_borrar_pedido=True,
            borrar_revisado_at=reviewed_at,
            borrar_revisado_por_id=active_user.id,
        ),
        "sin_marca": RmaCaso(numero_caso="RMA-2026-9103", estado="abierto", marcado_borrar_pedido=False),
        "marca_nula": RmaCaso(numero_caso="RMA-2026-9104", estado="abierto"),
        "eliminado": RmaCaso(numero_caso="RMA-2026-9105", estado="abierto", marcado_borrar_pedido=True, activo=False),
    }
    db.add_all(rows.values())
    db.flush()
    return rows


def _numeros(body: dict) -> list[str]:
    return [row["numero_caso"] for row in body["items"]]


@pytest.mark.parametrize(
    ("estado", "esperados"),
    [
        (None, ["RMA-2026-9101"]),
        ("pendientes", ["RMA-2026-9101"]),
        ("revisados", ["RMA-2026-9102"]),
        ("todos", ["RMA-2026-9102", "RMA-2026-9101"]),
    ],
)
def test_list_filters_marked_cases_and_counts_each_filter(client, auth_headers, casos, estado, esperados):
    params = {"estado": estado} if estado else {}
    with _permisos("rma.ver"):
        resp = client.get("/api/rma-seguimiento/para-borrar", params=params, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _numeros(body) == esperados
    assert body["counts"] == {"pendientes": 1, "revisados": 1, "todos": 2}


def test_list_says_who_reviewed_and_when(client, auth_headers, casos, active_user):
    with _permisos("rma.ver"):
        resp = client.get("/api/rma-seguimiento/para-borrar", params={"estado": "revisados"}, headers=auth_headers)

    row = resp.json()["items"][0]
    assert row["borrar_revisado_por_id"] == active_user.id
    assert row["borrar_revisado_por_nombre"] == active_user.nombre
    assert row["borrar_revisado_at"].startswith("2026-11-02T15:00:00")


def test_list_rejects_an_unknown_filter(client, auth_headers, casos):
    with _permisos("rma.ver"):
        resp = client.get("/api/rma-seguimiento/para-borrar", params={"estado": "otro"}, headers=auth_headers)
    assert resp.status_code == 422


def test_list_needs_the_rma_list_permission(client, auth_headers, casos):
    with _permisos():
        resp = client.get("/api/rma-seguimiento/para-borrar", headers=auth_headers)
    assert resp.status_code == 403


def test_ticking_revisado_stores_who_and_when_and_leaves_the_pending_list(client, auth_headers, db, casos, active_user):
    caso = casos["pendiente"]
    with _permisos("rma.ver", "rma.gestionar"):
        resp = client.put(
            f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": True}, headers=auth_headers
        )
        pendientes = client.get("/api/rma-seguimiento/para-borrar", headers=auth_headers).json()

    assert resp.status_code == 200, resp.text
    assert resp.json()["borrar_revisado_por_id"] == active_user.id
    assert resp.json()["borrar_revisado_at"] is not None
    db.expire_all()
    stored = db.get(RmaCaso, caso.id)
    assert stored.borrar_revisado_por_id == active_user.id
    assert stored.borrar_revisado_at is not None
    assert _numeros(pendientes) == []
    assert pendientes["counts"] == {"pendientes": 0, "revisados": 2, "todos": 2}


def test_unticking_revisado_clears_who_and_when(client, auth_headers, db, casos):
    caso = casos["revisado"]
    with _permisos("rma.gestionar"):
        resp = client.put(
            f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": False}, headers=auth_headers
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["borrar_revisado_at"] is None
    assert resp.json()["borrar_revisado_por_id"] is None
    db.expire_all()
    stored = db.get(RmaCaso, caso.id)
    assert stored.borrar_revisado_at is None
    assert stored.borrar_revisado_por_id is None


def test_ticking_needs_rma_gestionar(client, auth_headers, db, casos):
    caso = casos["pendiente"]
    with _permisos("rma.ver"):
        resp = client.put(
            f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": True}, headers=auth_headers
        )

    assert resp.status_code == 403
    db.expire_all()
    assert db.get(RmaCaso, caso.id).borrar_revisado_at is None


def test_ticking_an_unknown_case_is_404(client, auth_headers, casos):
    with _permisos("rma.gestionar"):
        resp = client.put("/api/rma-seguimiento/999999/borrar-revisado", json={"revisado": True}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.parametrize("cual", ["sin_marca", "marca_nula"])
def test_ticking_a_case_not_marked_para_borrar_is_404(client, auth_headers, db, casos, cual):
    caso = casos[cual]
    with _permisos("rma.gestionar"):
        resp = client.put(
            f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": True}, headers=auth_headers
        )

    assert resp.status_code == 404
    db.expire_all()
    assert db.get(RmaCaso, caso.id).borrar_revisado_at is None


def test_each_tick_is_logged_in_the_case_history(client, auth_headers, db, casos, active_user):
    caso = casos["pendiente"]
    with _permisos("rma.gestionar"):
        client.put(f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": True}, headers=auth_headers)
        client.put(f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": False}, headers=auth_headers)

    rows = (
        db.query(RmaCasoHistorial)
        .filter(RmaCasoHistorial.caso_id == caso.id, RmaCasoHistorial.campo == "borrar_revisado_at")
        .order_by(RmaCasoHistorial.id)
        .all()
    )
    assert [(r.valor_anterior is None, r.valor_nuevo is None, r.usuario_id) for r in rows] == [
        (True, False, active_user.id),
        (False, True, active_user.id),
    ]


def test_ticking_an_already_reviewed_case_records_the_new_reviewer(client, admin_auth_headers, db, casos, admin_user):
    caso = casos["revisado"]
    with _permisos("rma.gestionar"):
        resp = client.put(
            f"/api/rma-seguimiento/{caso.id}/borrar-revisado", json={"revisado": True}, headers=admin_auth_headers
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["borrar_revisado_por_id"] == admin_user.id
    db.expire_all()
    stored = db.get(RmaCaso, caso.id)
    assert stored.borrar_revisado_por_id == admin_user.id
    # The test database may hand back a naive timestamp: compare the wall-clock instant.
    assert stored.borrar_revisado_at.replace(tzinfo=None) > datetime(2026, 11, 2, 15, 0)
