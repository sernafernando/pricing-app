"""
Regression test: PUT /rma-seguimiento/{id} must persist client and order fields.

Bug: editing client data (cliente_nombre, cliente_dni, cust_id, cliente_numero)
or order data (ml_id, origen) on an existing caso silently dropped the values,
because those fields were missing from the CasoUpdate schema (and the frontend
PUT payload). `observaciones` saved fine only because it was whitelisted.

This locks the fix: every case-level field editable in the modal must
round-trip through PUT. The "cliente vacío que no se puede rellenar luego"
scenario is exercised by starting from a caso with no client data.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.models.rma_caso import RmaCaso


@contextmanager
def _con_permiso_rma():
    """Grant rma.gestionar for the duration of the request."""
    with patch(
        "app.services.permisos_service.PermisosService.tiene_permiso",
        return_value=True,
    ):
        yield


@pytest.fixture()
def caso_vacio(db) -> RmaCaso:
    """An existing caso with no client/order data — the 'cliente vacío' case."""
    caso = RmaCaso(numero_caso="RMA-2026-9001", estado="abierto")
    db.add(caso)
    db.flush()
    return caso


def test_put_persiste_datos_cliente_y_pedido(client, auth_headers, db, caso_vacio):
    """Filling client + order data on an existing caso must persist."""
    payload = {
        "cust_id": 12345,
        "cliente_nombre": "Juan Pérez",
        "cliente_dni": "20-12345678-9",
        "cliente_numero": 1155443322,
        "ml_id": "ML-998877",
        "origen": "mercadolibre",
    }

    with _con_permiso_rma():
        resp = client.put(
            f"/api/rma-seguimiento/{caso_vacio.id}",
            json=payload,
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key, value in payload.items():
        assert body[key] == value, f"{key} no se reflejó en la respuesta del PUT"

    db.expire_all()
    refrescado = db.query(RmaCaso).filter(RmaCaso.id == caso_vacio.id).first()
    assert refrescado.cust_id == 12345
    assert refrescado.cliente_nombre == "Juan Pérez"
    assert refrescado.cliente_dni == "20-12345678-9"
    assert refrescado.cliente_numero == 1155443322
    assert refrescado.ml_id == "ML-998877"
    assert refrescado.origen == "mercadolibre"


def test_put_observaciones_sigue_funcionando(client, auth_headers, db, caso_vacio):
    """Regression guard: the previously-working field keeps working."""
    with _con_permiso_rma():
        resp = client.put(
            f"/api/rma-seguimiento/{caso_vacio.id}",
            json={"observaciones": "Cliente reclama por garantía"},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["observaciones"] == "Cliente reclama por garantía"
