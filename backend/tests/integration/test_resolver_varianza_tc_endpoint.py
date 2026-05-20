"""
T2.22–T2.24 — Integration tests for POST /pedidos/{pedido_id}/resolver-varianza-tc (F2).

Verifies:
  - T2.22: happy path → 201 + NotaCreditoLocalResponse body.
  - T2.23: 409 when varianza == 0.
  - T2.24: 403 without permission.
  - 401 without authentication.

Pattern mirrors test_compras_endpoints.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import ordenes_pago_service

BASE = "/api/administracion/compras"


# ---------------------------------------------------------------------------
# Permission fixtures (same pattern as test_compras_endpoints.py)
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


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Endpoint Varianza", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        nombre="Prov Endpoint Varianza",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=886,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS Endpoint Varianza",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("50000000"),
        saldo_actual=Decimal("50000000"),
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
def tipo_cambio_usd(db) -> None:
    db.add(TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410")))
    db.add(TipoCambio(fecha=date(2026, 1, 2), moneda="USD", compra=Decimal("1450"), venta=Decimal("1460")))
    db.flush()


@pytest.fixture
def pedido_con_varianza(db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user) -> PedidoCompra:
    """Pedido USD 1000 with TC_orig=1400, TC_ef=1450, 999 USD Caso-B → varianza=+49950."""
    uid = active_user.id
    pedido = PedidoCompra(
        numero="PC-TEST-VAR-0001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=Decimal("1400"),
        tipo_cambio_original=Decimal("1400"),
        estado="aprobado",
        creado_por_id=uid,
    )
    db.add(pedido)
    db.flush()

    op_a = ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1450"),
        tipo_cambio=Decimal("1450"),
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("1450")}],
        creado_por_id=uid,
        actualizar_tc_pedido=True,
    )
    ordenes_pago_service.ejecutar_pago(
        db, orden_pago_id=op_a.id, caja_id=caja_ars.id, fecha_pago_real=date(2026, 1, 2), user_id=uid
    )
    db.flush()

    op_b = ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1448550"),
        tipo_cambio=Decimal("1450"),
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("1448550")}],
        creado_por_id=uid,
        actualizar_tc_pedido=False,
    )
    ordenes_pago_service.ejecutar_pago(
        db, orden_pago_id=op_b.id, caja_id=caja_ars.id, fecha_pago_real=date(2026, 1, 2), user_id=uid
    )
    db.flush()
    db.commit()
    return pedido


@pytest.fixture
def pedido_sin_varianza(db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user) -> PedidoCompra:
    """Pedido USD 1000 paid fully via Caso-A → varianza=0."""
    uid = active_user.id
    pedido = PedidoCompra(
        numero="PC-TEST-SIN-VAR-0001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=Decimal("1400"),
        tipo_cambio_original=Decimal("1400"),
        estado="aprobado",
        creado_por_id=uid,
    )
    db.add(pedido)
    db.flush()

    op = ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1450000"),
        tipo_cambio=Decimal("1450"),
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("1450000")}],
        creado_por_id=uid,
        actualizar_tc_pedido=True,
    )
    ordenes_pago_service.ejecutar_pago(
        db, orden_pago_id=op.id, caja_id=caja_ars.id, fecha_pago_real=date(2026, 1, 2), user_id=uid
    )
    db.flush()
    db.commit()
    return pedido


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolverVarianzaTCEndpoint:
    """T2.22–T2.24: POST /pedidos/{pedido_id}/resolver-varianza-tc."""

    def test_sin_auth_401(self, client, pedido_con_varianza):
        """T2.24 (401): unauthenticated request → 401 or 403."""
        r = client.post(f"{BASE}/pedidos/{pedido_con_varianza.id}/resolver-varianza-tc")
        assert r.status_code in (401, 403)

    def test_sin_permiso_403(self, client, auth_headers, pedido_con_varianza, sin_permisos):
        """T2.24 (403): authenticated but no permission → 403."""
        r = client.post(
            f"{BASE}/pedidos/{pedido_con_varianza.id}/resolver-varianza-tc",
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_happy_path_201(self, client, auth_headers, pedido_con_varianza, con_todos_los_permisos):
        """T2.22: positive varianza → 201 + NotaCreditoLocalResponse with tipo='debito'."""
        r = client.post(
            f"{BASE}/pedidos/{pedido_con_varianza.id}/resolver-varianza-tc",
            headers=auth_headers,
        )
        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["tipo"] == "debito", f"TC rose → ND expected, got tipo='{data['tipo']}'"
        assert Decimal(data["monto"]) == Decimal("49950")
        assert data["moneda"] == "ARS"
        assert data["estado"] in {"aprobado", "aplicada_parcial", "aplicada"}

    def test_no_varianza_409(self, client, auth_headers, pedido_sin_varianza, con_todos_los_permisos):
        """T2.23: varianza == 0 → 409 Conflict."""
        r = client.post(
            f"{BASE}/pedidos/{pedido_sin_varianza.id}/resolver-varianza-tc",
            headers=auth_headers,
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"

    def test_pedido_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        """404 when pedido not found."""
        r = client.post(
            f"{BASE}/pedidos/999999/resolver-varianza-tc",
            headers=auth_headers,
        )
        assert r.status_code == 404
