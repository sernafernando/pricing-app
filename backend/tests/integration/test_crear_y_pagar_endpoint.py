"""
T3.7–T3.9 — Integration tests for POST /ordenes-pago/crear-y-pagar (F3).

Verifies:
  - T3.7: happy path → HTTP 201, response includes OP and payment data.
  - T3.8: 400 on payment failure (non-existent caja) → zero DB writes.
  - T3.9: 403 without the required permissions.
  - 401 without authentication.

Pattern mirrors test_resolver_varianza_tc_endpoint.py.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor

BASE = "/api/administracion/compras"


# ---------------------------------------------------------------------------
# Permission fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con_todos_los_permisos():
    """Force PermisosService.tiene_permiso → True."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    """Force PermisosService.tiene_permiso → False."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def solo_ejecutar_pagos():
    """Only ejecutar_pagos granted (not gestionar_ordenes_compra).

    Verifies that the dual-permission requirement is enforced:
    crear-y-pagar needs BOTH permissions.
    """

    def _tiene_permiso(_user, permiso: str, **_kwargs) -> bool:
        return permiso == "administracion.ejecutar_pagos"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            side_effect=_tiene_permiso,
        ),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa CYP Endpoint", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        nombre="Prov CYP Endpoint",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=5678,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS CYP Endpoint",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("10000000"),
        saldo_actual=Decimal("10000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> None:
    td = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP", activo=True)
    db.add(td)
    db.flush()


@pytest.fixture
def pedido_ars(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Approved ARS pedido for one-step payment."""
    pedido = PedidoCompra(
        numero="PC-CYP-EP-0001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("8000"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()
    return pedido


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrearYPagarEndpoint:
    """T3.7–T3.9: POST /ordenes-pago/crear-y-pagar."""

    def test_sin_auth_401(self, client, empresa, proveedor, caja_ars, tipos_doc_caja, pedido_ars):
        """T3.9 (401): unauthenticated request → 401 or 403."""
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": caja_ars.id,
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code in (401, 403)

    def test_sin_permiso_403(
        self, client, auth_headers, empresa, proveedor, caja_ars, tipos_doc_caja, pedido_ars, sin_permisos
    ):
        """T3.9 (403): authenticated but no permission → 403."""
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": caja_ars.id,
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code == 403

    def test_happy_path_201(
        self, client, auth_headers, empresa, proveedor, caja_ars, tipos_doc_caja, pedido_ars, con_todos_los_permisos
    ):
        """T3.7: valid request → 201 + OP response with estado='pagado'."""
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": caja_ars.id,
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["estado"] == "pagado", f"Expected 'pagado', got '{data['estado']}'"
        assert data["caja_id"] == caja_ars.id
        assert data["fecha_pago_real"] == "2026-01-15"
        assert data["numero"].startswith("OP-")

    def test_happy_path_returns_op_number(
        self, client, auth_headers, empresa, proveedor, caja_ars, tipos_doc_caja, pedido_ars, con_todos_los_permisos
    ):
        """T3.7: response includes the OP numero."""
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": caja_ars.id,
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert "numero" in data
        assert "id" in data

    def test_solo_ejecutar_pagos_sin_gestionar_403(
        self, client, auth_headers, empresa, proveedor, caja_ars, tipos_doc_caja, pedido_ars, solo_ejecutar_pagos
    ):
        """T3.9 dual-perm: has ejecutar_pagos but not gestionar_ordenes_compra → 403."""
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": caja_ars.id,
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code == 403

    def test_payment_failure_bad_caja_400_or_404(
        self, client, auth_headers, empresa, proveedor, tipos_doc_caja, pedido_ars, con_todos_los_permisos
    ):
        """T3.8: non-existent caja → 400/404, full rollback.

        AC3.2: caja validation fails → HTTP error returned.
        The rollback atomicity is verified at the service layer (T3.4).
        """
        r = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "8000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": "8000"}],
                "caja_id": 999999,  # non-existent
                "fecha_pago_real": "2026-01-15",
            },
        )
        assert r.status_code in (400, 404, 422), f"Expected 400/404/422 on bad caja, got {r.status_code}: {r.text}"
