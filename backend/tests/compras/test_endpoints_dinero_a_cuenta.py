"""
T2.9 — Tests HTTP para los endpoints de dinero a cuenta y saldo-a-favor-breakdown.

Cubre:
  - test_get_dinero_a_cuenta_list_200
  - test_get_saldo_breakdown_200
  - test_requires_auth (401 sin token)
  - test_requires_permiso (403 sin permiso)

Patrón: igual a test_wipe_compras.py — usa client + patch de PermisosService.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.proveedor import Proveedor
# admin_user and admin_auth_headers are provided by tests/conftest.py

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
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


@pytest.fixture()
def sin_permiso_cc():
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=False,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Data fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa EP Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor EP Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def op_stub(db, empresa, proveedor, admin_user) -> object:
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido, creado_por_id)
            VALUES ('OP-EP-001', :emp, :prov, 'ARS', 5000,
                    'especifica', 'pagado', 0, :uid)
            """
        ),
        {"emp": empresa.id, "prov": proveedor.id, "uid": admin_user.id},
    )
    db.flush()
    op_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return type("OP", (), {"id": op_id})()


@pytest.fixture()
def dac_fixture(db, proveedor, empresa, admin_user, op_stub) -> DineroACuenta:
    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=Decimal("3000"),
        moneda="ARS",
        estado="disponible",
        origen_op_id=op_stub.id,
        creado_por_id=admin_user.id,
    )
    db.add(dac)
    db.flush()
    return dac


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestDineroACuentaEndpoints:
    def test_requires_auth_dinero_a_cuenta(self, client, proveedor):
        """401 o 403 sin Authorization header."""
        response = client.get(f"{BASE}/proveedores/{proveedor.id}/dinero-a-cuenta")
        assert response.status_code in (401, 403)

    def test_requires_auth_breakdown(self, client, proveedor):
        """401 o 403 sin Authorization header — breakdown."""
        response = client.get(f"{BASE}/proveedores/{proveedor.id}/saldo-a-favor-breakdown")
        assert response.status_code in (401, 403)

    def test_requires_permiso_dinero_a_cuenta(self, client, proveedor, admin_auth_headers, sin_permiso_cc):
        """403 con token pero sin permiso ver_cuentas_corrientes."""
        response = client.get(
            f"{BASE}/proveedores/{proveedor.id}/dinero-a-cuenta",
            headers=admin_auth_headers,
        )
        assert response.status_code == 403

    def test_requires_permiso_breakdown(self, client, proveedor, admin_auth_headers, sin_permiso_cc):
        """403 con token pero sin permiso — breakdown."""
        response = client.get(
            f"{BASE}/proveedores/{proveedor.id}/saldo-a-favor-breakdown",
            headers=admin_auth_headers,
        )
        assert response.status_code == 403

    def test_get_dinero_a_cuenta_list_200(self, client, proveedor, dac_fixture, admin_auth_headers, con_permiso_cc):
        """200 con lista de DACs. Al menos 1 fila con campos correctos."""
        response = client.get(
            f"{BASE}/proveedores/{proveedor.id}/dinero-a-cuenta",
            headers=admin_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        fila = data[0]
        assert fila["proveedor_id"] == proveedor.id
        assert fila["moneda"] == "ARS"
        assert fila["estado"] == "disponible"
        assert "saldo_disponible" in fila

    def test_get_saldo_breakdown_200(self, client, proveedor, dac_fixture, admin_auth_headers, con_permiso_cc):
        """200 con breakdown del saldo a favor."""
        response = client.get(
            f"{BASE}/proveedores/{proveedor.id}/saldo-a-favor-breakdown",
            headers=admin_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["proveedor_id"] == proveedor.id
        assert "saldo_a_favor_total_ars" in data
        assert "componente_dinero_a_cuenta_ars" in data
        assert "componente_nc_ars" in data
        # El DAC de 3000 debe aparecer en el componente
        assert float(data["componente_dinero_a_cuenta_ars"]) == 3000.0

    def test_get_dinero_a_cuenta_proveedor_inexistente(self, client, admin_auth_headers, con_permiso_cc):
        """404 para proveedor que no existe."""
        response = client.get(
            f"{BASE}/proveedores/999999/dinero-a-cuenta",
            headers=admin_auth_headers,
        )
        assert response.status_code == 404
