"""
RMA "Para borrar" view (owner, 2026-11-03): "necesito una vista sencilla de rma donde se vean los pedidos que se
marcan parar borrar ... y que tenga un tilde cuando ya se revisó para que no aparezca más" ... "(con un filtro claro)".

- GET /rma-seguimiento/para-borrar lists the active cases with `marcado_borrar_pedido`, filtered by
  pendientes (default) / revisados / todos, with the count of each.
- PUT /rma-seguimiento/{id}/borrar-revisado ticks or unticks "Revisado": it stores who and when, or clears both.
- Viewing needs rma.ver (like the RMA list); the tick needs rma.gestionar.

Grouped by ML operation (owner, 2026-11-06): "si pueden traer el número de envío de la operación ... y cuando es un
mismo pedido agruparlo juntos, no mostrar dos líneas, si bien son 2 RMA serían una misma operación". Each item is one
operation with its cases and articles and the shipping number from our stored ML orders; the counts count operations;
PUT /rma-seguimiento/para-borrar/revisado ticks every case of the row. An operation stays pending while any of its
cases is pending.
"""

from contextlib import contextmanager
from datetime import datetime, UTC
from unittest.mock import patch

import pytest

from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_caso_item import RmaCasoItem


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
    return [caso["numero_caso"] for row in body["items"] for caso in row["casos"]]


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

    row = resp.json()["items"][0]["casos"][0]
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


# ── Grouped by operation ──────────────────────────────────────────────────

PACK = "2000000000000001"
ORDEN_A = "2000000000000002"
ORDEN_B = "2000000000000003"
ENVIO = "40000000001"


@pytest.fixture()
def carrito(db, active_user) -> dict[str, RmaCaso]:
    """Two RMAs for the two articles of one ML cart (one order each, one pack, one shipment), the second already
    reviewed, plus a case whose ML id is no sale we store."""
    db.add_all(
        [
            MercadoLibreOrderHeader(comp_id=1, mlo_id=900001, mlorder_id=ORDEN_A, ml_pack_id=PACK),
            MercadoLibreOrderHeader(comp_id=1, mlo_id=900002, mlorder_id=ORDEN_B, ml_pack_id=PACK),
            MercadoLibreOrderShipping(comp_id=1, mlm_id=800001, mlo_id=900001, mlshippingid=ENVIO),
            MercadoLibreOrderShipping(comp_id=1, mlm_id=800002, mlo_id=900002, mlshippingid=ENVIO),
        ]
    )
    rows = {
        "a": RmaCaso(
            numero_caso="RMA-2026-9201",
            estado="abierto",
            cliente_nombre="Cliente Prueba",
            ml_id=ORDEN_A,
            marcado_borrar_pedido=True,
            items=[RmaCasoItem(producto_desc="Router AX1500")],
        ),
        "b": RmaCaso(
            numero_caso="RMA-2026-9202",
            estado="abierto",
            cliente_nombre="Cliente Prueba",
            ml_id=ORDEN_B,
            marcado_borrar_pedido=True,
            borrar_revisado_at=datetime(2026, 11, 2, 15, 0, tzinfo=UTC),
            borrar_revisado_por_id=active_user.id,
            items=[RmaCasoItem(producto_desc="Repetidor RE200")],
        ),
        "suelto": RmaCaso(numero_caso="RMA-2026-9203", estado="abierto", ml_id="ML-998877", marcado_borrar_pedido=True),
    }
    db.add_all(rows.values())
    db.flush()
    return rows


def _todos(client, auth_headers) -> dict:
    with _permisos("rma.ver"):
        resp = client.get("/api/rma-seguimiento/para-borrar", params={"estado": "todos"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cases_of_one_operation_are_one_row_with_the_shipping_number_and_articles(client, auth_headers, carrito):
    body = _todos(client, auth_headers)

    assert [[c["numero_caso"] for c in row["casos"]] for row in body["items"]] == [
        ["RMA-2026-9203"],
        ["RMA-2026-9202", "RMA-2026-9201"],
    ]
    operacion = body["items"][1]
    assert operacion["numero_envio"] == ENVIO
    assert operacion["cliente_nombre"] == "Cliente Prueba"
    assert [c["articulos"] for c in operacion["casos"]] == [["Repetidor RE200"], ["Router AX1500"]]
    assert body["counts"] == {"pendientes": 2, "revisados": 0, "todos": 2}


def test_a_case_with_no_stored_sale_is_listed_without_a_shipping_number(client, auth_headers, carrito):
    suelto = _todos(client, auth_headers)["items"][0]

    assert suelto["ml_id"] == "ML-998877"
    assert suelto["numero_envio"] is None


def test_two_cases_with_the_same_unmatched_ml_id_are_still_one_row(client, auth_headers, db, carrito):
    db.add(RmaCaso(numero_caso="RMA-2026-9204", estado="abierto", ml_id="ML-998877", marcado_borrar_pedido=True))
    db.flush()

    body = _todos(client, auth_headers)

    assert [c["numero_caso"] for c in body["items"][0]["casos"]] == ["RMA-2026-9204", "RMA-2026-9203"]
    assert body["counts"]["todos"] == 2


def test_an_operation_with_a_pending_case_stays_pending_with_all_its_cases(client, auth_headers, carrito):
    with _permisos("rma.ver"):
        pendientes = client.get("/api/rma-seguimiento/para-borrar", headers=auth_headers).json()
        revisados = client.get(
            "/api/rma-seguimiento/para-borrar", params={"estado": "revisados"}, headers=auth_headers
        ).json()

    assert _numeros(pendientes) == ["RMA-2026-9203", "RMA-2026-9202", "RMA-2026-9201"]
    assert [row["revisado"] for row in pendientes["items"]] == [False, False]
    assert _numeros(revisados) == []


def test_ticking_the_row_reviews_every_case_of_the_operation(client, auth_headers, db, carrito, active_user):
    a, b = carrito["a"], carrito["b"]
    revisado_antes = b.borrar_revisado_at
    with _permisos("rma.ver", "rma.gestionar"):
        resp = client.put(
            "/api/rma-seguimiento/para-borrar/revisado",
            json={"caso_ids": [a.id, b.id], "revisado": True},
            headers=auth_headers,
        )
        revisados = client.get(
            "/api/rma-seguimiento/para-borrar", params={"estado": "revisados"}, headers=auth_headers
        ).json()

    assert resp.status_code == 200, resp.text
    db.expire_all()
    assert db.get(RmaCaso, a.id).borrar_revisado_por_id == active_user.id
    # A case already reviewed keeps who reviewed it and when.
    assert db.get(RmaCaso, b.id).borrar_revisado_at.replace(tzinfo=None) == revisado_antes.replace(tzinfo=None)
    assert _numeros(revisados) == ["RMA-2026-9202", "RMA-2026-9201"]
    assert revisados["items"][0]["revisado"] is True
    historial = db.query(RmaCasoHistorial).filter(RmaCasoHistorial.campo == "borrar_revisado_at").all()
    assert [(h.caso_id, h.usuario_id) for h in historial] == [(a.id, active_user.id)]


def test_unticking_the_row_clears_every_case_of_the_operation(client, auth_headers, db, carrito):
    a, b = carrito["a"], carrito["b"]
    with _permisos("rma.gestionar"):
        client.put(
            "/api/rma-seguimiento/para-borrar/revisado",
            json={"caso_ids": [a.id, b.id], "revisado": True},
            headers=auth_headers,
        )
        resp = client.put(
            "/api/rma-seguimiento/para-borrar/revisado",
            json={"caso_ids": [a.id, b.id], "revisado": False},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    db.expire_all()
    assert [db.get(RmaCaso, c.id).borrar_revisado_at for c in (a, b)] == [None, None]
    assert [db.get(RmaCaso, c.id).borrar_revisado_por_id for c in (a, b)] == [None, None]


def test_ticking_the_row_needs_rma_gestionar(client, auth_headers, db, carrito):
    a = carrito["a"]
    with _permisos("rma.ver"):
        resp = client.put(
            "/api/rma-seguimiento/para-borrar/revisado",
            json={"caso_ids": [a.id], "revisado": True},
            headers=auth_headers,
        )

    assert resp.status_code == 403
    db.expire_all()
    assert db.get(RmaCaso, a.id).borrar_revisado_at is None


def test_ticking_a_row_with_a_case_not_marked_changes_nothing(client, auth_headers, db, carrito, casos):
    a = carrito["a"]
    with _permisos("rma.gestionar"):
        resp = client.put(
            "/api/rma-seguimiento/para-borrar/revisado",
            json={"caso_ids": [a.id, casos["sin_marca"].id], "revisado": True},
            headers=auth_headers,
        )

    assert resp.status_code == 404
    db.expire_all()
    assert db.get(RmaCaso, a.id).borrar_revisado_at is None


def test_the_list_reads_cases_and_sales_in_a_fixed_number_of_queries(client, auth_headers, db, carrito):
    from sqlalchemy import event

    def contar() -> int:
        statements: list[str] = []
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(db.get_bind(), "before_cursor_execute", listener)
        try:
            _todos(client, auth_headers)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", listener)
        return len([s for s in statements if "rma_casos" in s or "tb_mercadolibre" in s or "rma_caso_items" in s])

    antes = contar()
    for n in range(5):
        db.add(
            RmaCaso(
                numero_caso=f"RMA-2026-93{n:02d}",
                estado="abierto",
                ml_id=f"ML-{n}",
                marcado_borrar_pedido=True,
                items=[RmaCasoItem(producto_desc=f"Artículo {n}")],
            )
        )
    db.flush()

    assert contar() == antes
