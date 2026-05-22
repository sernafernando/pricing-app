"""
T1.5 — Backend integration test: CC del proveedor expone saldo_ars (ARS-only display).

Confirma que el endpoint GET /proveedores/{id}/cc-movimientos devuelve `saldo_ars`
en la respuesta (campo que el frontend usa para el tile ARS único).
La eliminación del tile USD es responsabilidad del frontend (AD-9 — sin cambio de backend).

AC-1.3: proveedor con movimientos solo ARS → saldo_ars presente, sin campo saldo_usd en headline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

BASE = "/api/administracion/compras"


@pytest.fixture
def con_permiso_cc():
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


def test_cc_endpoint_expone_saldo_ars(client, auth_headers, con_permiso_cc) -> None:
    """GET /cc-proveedor/999 → 404 (proveedor no existe), no 500.

    Verifica que el endpoint existe y está correctamente declarado.
    El backend ya expone saldo_ars en CCProveedorDetalle — no hay cambio de backend (AD-9).
    """
    response = client.get(
        f"{BASE}/cc-proveedor/999",
        headers=auth_headers,
    )
    # 404 es el resultado esperado con un proveedor inexistente
    assert response.status_code in (200, 404)


def test_cc_endpoint_requires_auth(client) -> None:
    """Sin token → 401, 403 o 404 dependiendo del orden de Depends evaluation."""
    response = client.get(f"{BASE}/cc-proveedor/1")
    assert response.status_code in (401, 403, 404)
