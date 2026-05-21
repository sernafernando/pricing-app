"""
T3.4 — Integration tests para F7 PR#2b: ejecutar_pago y crear_y_pagar con banco.

Cubre:
  - POST /ordenes-pago/{op_id}/pagar con banco_id → 200; OP updated; BancoMovimiento in DB.
  - POST /ordenes-pago/{op_id}/pagar con caja_id → regression (AC-F2-6).
  - Both caja_id + banco_id → 422 (AC-F2-7).
  - POST /ordenes-pago/crear-y-pagar con banco_id → OP created+paid with banco.
  - POST /ordenes-pago/crear-y-pagar con banco_id + ncs_aplicadas → full combo (Scenario H).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.banco_movimiento import BancoMovimiento
from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Data fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaBancoInt", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorBancoInt",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=88888,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def tipos_doc_caja(db) -> None:
    for nombre in ("Orden de Pago", "Orden de Pago Anulada"):
        existing = db.query(CajaTipoDocumento).filter(CajaTipoDocumento.nombre == nombre).first()
        if not existing:
            db.add(CajaTipoDocumento(nombre=nombre, descripcion=nombre, activo=True))
    db.flush()


@pytest.fixture
def caja(db, empresa, tipos_doc_caja) -> Caja:
    c = Caja(
        nombre="CajaBancoInt",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("1000000"),
        saldo_actual=Decimal("1000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        banco="Banco Test Int",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("500000"),
        saldo_actual=Decimal("500000"),
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="PC-BANCO-INT-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("30000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        numero="NC-BANCO-INT-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Integration test banco",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


@pytest.fixture
def op_pendiente(db, empresa, proveedor, active_user) -> OrdenPago:
    """OP pendiente a_cuenta — lista para ser pagada."""
    from app.services.numeracion_service import generar_siguiente_numero  # noqa: PLC0415

    numero, _ = generar_siguiente_numero(db, tipo="orden_pago", empresa_id=empresa.id)
    op = OrdenPago(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("20000"),
        modo_imputacion="a_cuenta",
        estado="pendiente",
        creado_por_id=active_user.id,
    )
    db.add(op)
    db.flush()
    return op


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestPagarConBancoEndpoint:
    """POST /ordenes-pago/{op_id}/pagar con banco_id."""

    def test_pagar_con_banco_200(
        self, client, auth_headers, db, empresa, proveedor, banco, op_pendiente, active_user, con_todos_los_permisos
    ) -> None:
        """
        Happy path (Scenario G): POST /pagar con banco_id.
        OP updated with banco_id; BancoMovimiento created in DB.
        """
        payload = {
            "banco_id": banco.id,
            "fecha_pago_real": "2026-05-21",
        }
        resp = client.post(
            f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        db.expire_all()
        op_db = db.get(OrdenPago, op_pendiente.id)
        assert op_db.estado == "pagado"
        assert op_db.banco_id == banco.id
        assert op_db.banco_movimiento_id is not None
        assert op_db.caja_id is None
        assert op_db.caja_documento_id is None  # AD-8

        # BancoMovimiento in DB
        mov = db.get(BancoMovimiento, op_db.banco_movimiento_id)
        assert mov is not None
        assert mov.tipo == "egreso"
        assert Decimal(str(mov.monto)) == Decimal("20000")

        # banco saldo updated
        db.expire_all()
        banco_db = db.get(BancoEmpresa, banco.id)
        assert Decimal(str(banco_db.saldo_actual)) == Decimal("480000")  # 500000 - 20000

    def test_pagar_con_caja_regression(
        self, client, auth_headers, db, empresa, proveedor, caja, op_pendiente, active_user, con_todos_los_permisos
    ) -> None:
        """
        Regression (AC-F2-6): POST /pagar con caja_id works as before.
        banco_id and banco_movimiento_id stay None.
        """
        payload = {
            "caja_id": caja.id,
            "fecha_pago_real": "2026-05-21",
        }
        resp = client.post(
            f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        db.expire_all()
        op_db = db.get(OrdenPago, op_pendiente.id)
        assert op_db.estado == "pagado"
        assert op_db.caja_id == caja.id
        assert op_db.caja_movimiento_id is not None
        assert op_db.banco_id is None
        assert op_db.banco_movimiento_id is None

    def test_both_caja_and_banco_422(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja,
        banco,
        op_pendiente,
        active_user,
        con_todos_los_permisos,
    ) -> None:
        """
        Both caja_id and banco_id → 422 (AC-F2-7).
        """
        payload = {
            "caja_id": caja.id,
            "banco_id": banco.id,
            "fecha_pago_real": "2026-05-21",
        }
        resp = client.post(
            f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestCrearYPagarConBancoEndpoint:
    """POST /ordenes-pago/crear-y-pagar con banco_id."""

    def test_crear_y_pagar_con_banco(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        """
        POST /crear-y-pagar con banco_id → OP created and paid with banco.
        """
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": 15000,
            "modo_imputacion": "a_cuenta",
            "banco_id": banco.id,
            "fecha_pago_real": "2026-05-21",
        }
        resp = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["estado"] == "pagado"
        assert data["banco_id"] == banco.id
        assert data["banco_movimiento_id"] is not None
        assert data.get("caja_id") is None

    def test_crear_y_pagar_con_banco_y_nc(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        banco,
        pedido,
        nc_aprobada,
        active_user,
        con_todos_los_permisos,
    ) -> None:
        """
        Scenario H: crear_y_pagar con banco_id + ncs_aplicadas → full combo.
        BancoMovimiento egreso + imputación NC→pedido in DB.
        """
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": 10000,
            "modo_imputacion": "especifica",
            "items": [{"tipo": "pedido_compra", "id": pedido.id, "monto": 10000}],
            "banco_id": banco.id,
            "fecha_pago_real": "2026-05-21",
            "ncs_aplicadas": [{"nc_id": nc_aprobada.id, "monto": 5000, "pedido_id": pedido.id}],
        }
        resp = client.post(
            f"{BASE}/ordenes-pago/crear-y-pagar",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["estado"] == "pagado"
        assert data["banco_id"] == banco.id

        # BancoMovimiento created
        op_id = data["id"]
        db.expire_all()
        op_db = db.get(OrdenPago, op_id)
        mov = db.get(BancoMovimiento, op_db.banco_movimiento_id)
        assert mov is not None
        assert Decimal(str(mov.monto)) == Decimal("10000")

        # NC imputada
        from app.models.imputacion import Imputacion  # noqa: PLC0415

        nc_imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "nota_credito_local",
                Imputacion.origen_id == nc_aprobada.id,
            )
            .first()
        )
        assert nc_imp is not None
