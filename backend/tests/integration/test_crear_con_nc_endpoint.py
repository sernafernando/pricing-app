"""
T1.5 — Integration tests para F7: crear OP y crear_y_pagar con ncs_aplicadas.

Cubre:
  - POST /ordenes-pago con ncs_aplicadas → 201, imputación NC→pedido en BD.
  - POST /ordenes-pago/crear-y-pagar con ncs_aplicadas → pagada, NC saldo reducido.
  - POST /ordenes-pago ncs_aplicadas = [] → 201 sin imputaciones NC (regresión).
  - Rollback end-to-end: NC con saldo insuficiente → 422, OP absent de BD.
  - POST /ordenes-pago/{op_id}/aplicar-nc → mismo resultado que antes (AC-F1-9 regresión).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
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
    e = Empresa(nombre="EmpresaF7Int", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorF7Int",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=9999,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def tipos_doc_caja(db) -> None:
    for nombre in ("Orden de Pago", "Orden de Pago Anulada"):
        db.add(CajaTipoDocumento(nombre=nombre, descripcion=nombre, activo=True))
    db.flush()


@pytest.fixture
def caja(db, empresa, tipos_doc_caja) -> Caja:
    c = Caja(
        nombre="CajaF7Int",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("5000000"),
        saldo_actual=Decimal("5000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="PC-F7INT-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("20000"),
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
        numero="NC-F7INT-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Integration test F7",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestCrearOPConNCEndpoint:
    """T1.5 — POST /ordenes-pago con ncs_aplicadas."""

    def test_crear_sin_ncs_201_sin_imputaciones_nc(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos
    ) -> None:
        """ncs_aplicadas = [] → 201, sin imputaciones NC (regresión existente)."""
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": "10000",
            "modo_imputacion": "a_cuenta",
            "items": [],
            "ncs_aplicadas": [],
        }
        resp = client.post(f"{BASE}/ordenes-pago", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

        nc_imps = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "nota_credito_local",
            )
            .all()
        )
        assert len(nc_imps) == 0

    def test_crear_con_nc_201_imputacion_creada(
        self, client, auth_headers, db, empresa, proveedor, pedido, nc_aprobada, active_user, con_todos_los_permisos
    ) -> None:
        """POST /ordenes-pago con ncs_aplicadas → 201, imputación NC→pedido en BD."""
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": "10000",
            "modo_imputacion": "a_cuenta",
            "items": [],
            "ncs_aplicadas": [{"nc_id": nc_aprobada.id, "monto": "3000", "pedido_id": pedido.id}],
        }
        resp = client.post(f"{BASE}/ordenes-pago", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

        nc_imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "nota_credito_local",
                Imputacion.origen_id == nc_aprobada.id,
            )
            .one_or_none()
        )
        assert nc_imp is not None
        assert nc_imp.monto_imputado == Decimal("3000")
        assert nc_imp.destino_tipo == "pedido_compra"
        assert nc_imp.destino_id == pedido.id

    def test_crear_nc_saldo_insuficiente_422(
        self, client, auth_headers, db, empresa, proveedor, pedido, nc_aprobada, active_user, con_todos_los_permisos
    ) -> None:
        """NC con monto > saldo → 422, OP ausente en BD."""
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": "10000",
            "modo_imputacion": "a_cuenta",
            "items": [],
            "ncs_aplicadas": [{"nc_id": nc_aprobada.id, "monto": "999999", "pedido_id": pedido.id}],
        }
        resp = client.post(f"{BASE}/ordenes-pago", json=payload, headers=auth_headers)
        assert resp.status_code == 422, resp.text

        # OP should not exist in DB
        ops = db.query(OrdenPago).filter(OrdenPago.proveedor_id == proveedor.id).all()
        assert len(ops) == 0


class TestCrearYPagarConNCEndpoint:
    """T1.5 — POST /ordenes-pago/crear-y-pagar con ncs_aplicadas."""

    def test_crear_y_pagar_con_nc(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja,
        pedido,
        nc_aprobada,
        active_user,
        con_todos_los_permisos,
    ) -> None:
        """crear-y-pagar + ncs_aplicadas → pagada, NC saldo reducido.

        New model (AD-NC-01): NC is subtractive from the OP cash.
        pago_a_cuenta=8000, NC=2000 → monto_total = 8000 - 2000 = 6000.
        Only 6000 is debited from caja; 2000 is covered by the NC credit.
        """
        # NC cubre 2000; pago_a_cuenta 8000: net cash = 8000 - 2000 = 6000
        payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": "6000",
            "modo_imputacion": "especifica",
            "items": [{"tipo": "pago_a_cuenta", "id": None, "monto": "8000"}],
            "caja_id": caja.id,
            "fecha_pago_real": "2026-05-21",
            "ncs_aplicadas": [{"nc_id": nc_aprobada.id, "monto": "2000", "pedido_id": pedido.id}],
        }
        resp = client.post(f"{BASE}/ordenes-pago/crear-y-pagar", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["estado"] == "pagado"

        nc_imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "nota_credito_local",
                Imputacion.origen_id == nc_aprobada.id,
            )
            .one_or_none()
        )
        assert nc_imp is not None
        assert nc_imp.monto_imputado == Decimal("2000")

    def test_aplicar_nc_desde_op_existente_regresion(
        self, client, auth_headers, db, empresa, proveedor, caja, active_user, con_todos_los_permisos
    ) -> None:
        """POST /ordenes-pago/{op_id}/aplicar-nc sigue funcionando (AC-F1-9 regresión)."""
        # Create a paid OP first
        pedido_r = PedidoCompra(
            numero="PC-F7REG-00001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("10000"),
            tipo_cambio=None,
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_r)
        nc_r = NotaCreditoLocal(
            numero="NC-F7REG-00001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("3000"),
            fecha_emision=date(2026, 1, 10),
            motivo="Regresión F7",
            estado="aprobado",
            tipo="credito",
            creado_por_id=active_user.id,
        )
        db.add(nc_r)
        db.flush()

        # Create OP with caja_id via crear-y-pagar (no NCs)
        create_payload = {
            "empresa_id": empresa.id,
            "proveedor_id": proveedor.id,
            "moneda": "ARS",
            "monto_total": "5000",
            "modo_imputacion": "especifica",
            "items": [{"tipo": "pedido_compra", "id": pedido_r.id, "monto": "5000"}],
            "caja_id": caja.id,
            "fecha_pago_real": "2026-05-21",
            "ncs_aplicadas": [],
        }
        resp = client.post(f"{BASE}/ordenes-pago/crear-y-pagar", json=create_payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        op_id = resp.json()["id"]

        # Apply NC via existing post-pay endpoint
        apply_payload = {"nc_id": nc_r.id, "monto": "1500"}
        resp2 = client.post(f"{BASE}/ordenes-pago/{op_id}/aplicar-nc", json=apply_payload, headers=auth_headers)
        assert resp2.status_code == 201, resp2.text
        data2 = resp2.json()
        assert "imputacion_id" in data2
        assert "nc_estado" in data2
