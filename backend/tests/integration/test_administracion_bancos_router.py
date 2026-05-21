"""
T2.4 — Integration tests for the administracion_bancos router (F7/PR#2a).

Covers:
- Permission fix: ver_caja (not ver_proveedores) for GET
- Permission fix: gestionar_caja (not gestionar_proveedores) for POST/PUT
- empresa_id filter on GET /administracion/bancos
- POST/PUT accept empresa_id
- GET/POST movimientos endpoints
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.banco_empresa import BancoEmpresa


BASE = "/api/administracion/bancos"


# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture
def con_todos_los_permisos():
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
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


def _permiso_solo(permiso_ok: str):
    """Context manager: only the given permiso returns True."""
    return patch(
        "app.services.permisos_service.PermisosService.tiene_permiso",
        side_effect=lambda self_or_user, *args, **kwargs: args[0] == permiso_ok if args else False,
    )


@pytest.fixture
def empresa_id(db) -> int:
    """Returns an empresa id that exists in the DB (creates one if needed)."""
    from app.models.empresa import Empresa  # noqa: PLC0415

    e = Empresa(nombre="Empresa Test Bancos", activo=True)
    db.add(e)
    db.flush()
    return e.id


@pytest.fixture
def banco_seed(db, empresa_id) -> BancoEmpresa:
    b = BancoEmpresa(
        banco="Santander",
        moneda="ARS",
        saldo_inicial=Decimal("0"),
        saldo_actual=Decimal("0"),
        empresa_id=empresa_id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def banco_sin_empresa(db) -> BancoEmpresa:
    b = BancoEmpresa(
        banco="HSBC Sin Empresa",
        moneda="ARS",
        saldo_inicial=Decimal("0"),
        saldo_actual=Decimal("0"),
        empresa_id=None,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


# ==========================================================================
# Permission tests — GET
# ==========================================================================


class TestGetPermissions:
    def test_get_bancos_sin_token_401_o_403(self, client) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_get_bancos_ver_caja_200(self, client, auth_headers, con_todos_los_permisos) -> None:
        """GET /administracion/bancos requires administracion.ver_caja (AC-F2-13)."""
        r = client.get(BASE, headers=auth_headers)
        assert r.status_code == 200

    def test_get_bancos_solo_ver_proveedores_403(self, client, auth_headers) -> None:
        """ver_proveedores alone is NOT sufficient for bancos — must be 403."""
        with _permiso_solo("administracion.ver_proveedores"):
            r = client.get(BASE, headers=auth_headers)
        assert r.status_code == 403

    def test_get_banco_by_id_sin_permiso_403(self, client, auth_headers, banco_seed, sin_permisos) -> None:
        r = client.get(f"{BASE}/{banco_seed.id}", headers=auth_headers)
        assert r.status_code == 403


# ==========================================================================
# Permission tests — POST/PUT
# ==========================================================================


class TestWritePermissions:
    def test_post_banco_gestionar_caja_201(self, client, auth_headers, con_todos_los_permisos) -> None:
        """POST /administracion/bancos requires administracion.gestionar_caja."""
        payload = {"banco": "Galicia", "moneda": "ARS", "saldo_inicial": 0}
        r = client.post(BASE, json=payload, headers=auth_headers)
        assert r.status_code == 201

    def test_post_banco_solo_gestionar_proveedores_403(self, client, auth_headers) -> None:
        """gestionar_proveedores alone is NOT sufficient for bancos — must be 403."""
        with _permiso_solo("administracion.gestionar_proveedores"):
            payload = {"banco": "BBVA", "moneda": "ARS", "saldo_inicial": 0}
            r = client.post(BASE, json=payload, headers=auth_headers)
        assert r.status_code == 403

    def test_put_banco_gestionar_caja_200(self, client, auth_headers, banco_seed, con_todos_los_permisos) -> None:
        r = client.put(f"{BASE}/{banco_seed.id}", json={"banco": "Santander Updated"}, headers=auth_headers)
        assert r.status_code == 200


# ==========================================================================
# empresa_id filter
# ==========================================================================


class TestEmpresaIdFilter:
    def test_empresa_id_filter_returns_matching_banco(
        self, client, auth_headers, banco_seed, banco_sin_empresa, empresa_id, con_todos_los_permisos
    ) -> None:
        """GET ?empresa_id=<eid> returns only bancos with that empresa_id."""
        r = client.get(f"{BASE}?empresa_id={empresa_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        ids = [b["id"] for b in data["bancos"]]
        assert banco_seed.id in ids
        assert banco_sin_empresa.id not in ids

    def test_empresa_id_filter_excludes_null_empresa(
        self, client, auth_headers, banco_seed, banco_sin_empresa, empresa_id, con_todos_los_permisos
    ) -> None:
        """GET ?empresa_id=<eid> excludes bancos with empresa_id=NULL."""
        r = client.get(f"{BASE}?empresa_id={empresa_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        ids = [b["id"] for b in data["bancos"]]
        assert banco_sin_empresa.id not in ids


# ==========================================================================
# empresa_id in create/update
# ==========================================================================


class TestEmpresaIdCreateUpdate:
    def test_post_banco_with_empresa_id_persists(
        self, client, auth_headers, empresa_id, con_todos_los_permisos, db
    ) -> None:
        payload = {"banco": "Patagonia", "moneda": "ARS", "saldo_inicial": 0, "empresa_id": empresa_id}
        r = client.post(BASE, json=payload, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data["empresa_id"] == empresa_id

    def test_put_banco_updates_empresa_id(
        self, client, auth_headers, banco_seed, empresa_id, con_todos_los_permisos
    ) -> None:
        r = client.put(f"{BASE}/{banco_seed.id}", json={"empresa_id": empresa_id}, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["empresa_id"] == empresa_id


# ==========================================================================
# Movimientos endpoints
# ==========================================================================


class TestMovimientosEndpoints:
    def test_get_movimientos_ver_caja_200(self, client, auth_headers, banco_seed, con_todos_los_permisos) -> None:
        r = client.get(f"{BASE}/{banco_seed.id}/movimientos", headers=auth_headers)
        assert r.status_code == 200

    def test_get_movimientos_sin_permiso_403(self, client, auth_headers, banco_seed, sin_permisos) -> None:
        r = client.get(f"{BASE}/{banco_seed.id}/movimientos", headers=auth_headers)
        assert r.status_code == 403

    def test_post_movimiento_creates_banco_movimiento(
        self, client, auth_headers, banco_seed, con_todos_los_permisos, db
    ) -> None:
        from datetime import date  # noqa: PLC0415

        payload = {
            "fecha": str(date.today()),
            "detalle": "Transferencia de prueba",
            "tipo": "ingreso",
            "monto": 1000.0,
        }
        r = client.post(f"{BASE}/{banco_seed.id}/movimientos", json=payload, headers=auth_headers)
        assert r.status_code == 201

        # Verify saldo_actual updated
        db.refresh(banco_seed)
        assert float(banco_seed.saldo_actual) == 1000.0
