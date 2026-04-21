"""
Integration tests del endpoint GET /administracion/proveedores/{id}/bancos.

Este endpoint es consumido por `ModalEjecutarPago` (Batch G, frontend)
para mostrar CBU/alias/cuenta del proveedor al momento de pagar. Es
crítico que devuelva los datos correctos y respete permisos y el filtro
`activo=True`.

Patrón: mismo estilo que `test_compras_endpoints.py` — auth_headers via
conftest, permisos mockeados a nivel `PermisosService.tiene_permiso`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.proveedor import Proveedor
from app.models.proveedor_banco import ProveedorBanco


# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture
def con_todos_los_permisos():
    """Forza `PermisosService.tiene_permiso → True`."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permisos():
    """Forza `PermisosService.tiene_permiso → False`."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="Proveedor Bancos Test", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def bancos_seed(db, proveedor) -> list[ProveedorBanco]:
    """Crea 3 bancos para el proveedor: 2 activos (uno con CBU, otro con alias)
    y 1 inactivo que debe quedar excluido."""
    bancos = [
        ProveedorBanco(
            proveedor_id=proveedor.id,
            banco="Santander",
            tipo_cuenta="CA $",
            cbu="0720123456789012345678",
            alias="PROV.SANTANDER.ARS",
            numero_cuenta="12345-6",
            sucursal="Centro",
            activo=True,
        ),
        ProveedorBanco(
            proveedor_id=proveedor.id,
            banco="Galicia",
            tipo_cuenta="CC $",
            cbu=None,
            alias="PROV.GALICIA.ARS",
            numero_cuenta="99999",
            sucursal=None,
            activo=True,
        ),
        ProveedorBanco(
            proveedor_id=proveedor.id,
            banco="BBVA (viejo)",
            tipo_cuenta="CA $",
            cbu="0170999999999999999999",
            alias="PROV.BBVA.VIEJO",
            activo=False,
        ),
    ]
    db.add_all(bancos)
    db.flush()
    return bancos


BASE = "/api/administracion/proveedores"


# ==========================================================================
# Tests
# ==========================================================================


class TestListarBancosProveedor:
    def test_listar_bancos_sin_token_401(self, client, proveedor):
        r = client.get(f"{BASE}/{proveedor.id}/bancos")
        assert r.status_code in (401, 403)

    def test_listar_bancos_sin_permiso_403(self, client, auth_headers, proveedor, sin_permisos):
        r = client.get(f"{BASE}/{proveedor.id}/bancos", headers=auth_headers)
        assert r.status_code == 403

    def test_listar_bancos_happy_ordena_por_banco_y_filtra_inactivos(
        self, client, auth_headers, proveedor, bancos_seed, con_todos_los_permisos
    ):
        """Happy path: devuelve solo activos, ordenado alfabéticamente por banco.

        El frontend (ModalEjecutarPago panel de bancos) depende de este orden
        estable para que tesorería vea siempre los mismos datos primero.
        """
        r = client.get(f"{BASE}/{proveedor.id}/bancos", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()

        assert isinstance(data, list)
        # "BBVA (viejo)" es activo=False → excluido.
        assert len(data) == 2

        # Orden alfabético por `banco`: Galicia < Santander.
        assert data[0]["banco"] == "Galicia"
        assert data[1]["banco"] == "Santander"

        # Campos requeridos por el frontend para copiar al homebanking.
        santander = data[1]
        assert santander["cbu"] == "0720123456789012345678"
        assert santander["alias"] == "PROV.SANTANDER.ARS"
        assert santander["numero_cuenta"] == "12345-6"
        assert santander["tipo_cuenta"] == "CA $"
        assert santander["activo"] is True
