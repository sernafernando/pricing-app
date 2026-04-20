"""
Tests de `ordenes_pago_service` (COMPRAS-4.4 + 4.5 + 4.6).

Cubre:
  - `crear`: modos especifica/a_cuenta/mixta + validaciones.
  - `detectar_duplicado_erp`: query anti-doble-contabilización.
  - `crear` con flag `confirmar_duplicado`.
  - `ejecutar_pago`: happy path + rollback, cross-moneda, estados.
  - `anular`: reverso completo (caja ingreso + imputaciones revertidas).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.caja import Caja, CajaMovimiento, CajaTipoDocumento
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa OP Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Proveedor OP", activo=True, origen=OrigenProveedor.ERP.value, supp_id=500)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        id=1,
        nombre="Caja ARS",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("100000"),
        saldo_actual=Decimal("100000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def caja_usd(db, empresa) -> Caja:
    caja = Caja(
        id=2,
        nombre="Caja USD",
        empresa_id=empresa.id,
        moneda="USD",
        saldo_inicial=Decimal("10000"),
        saldo_actual=Decimal("10000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> dict:
    td_op = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP pago", activo=True)
    td_op_anul = CajaTipoDocumento(nombre="Orden de Pago Anulada", descripcion="OP anulada", activo=True)
    db.add_all([td_op, td_op_anul])
    db.flush()
    return {"op": td_op, "anulada": td_op_anul}


@pytest.fixture
def pedido_aprobado(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-01-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        estado="aprobado",
        aprobado_por_id=active_user.id,
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


# ──────────────────────────────────────────────────────────────────────────
# crear — modos y validaciones
# ──────────────────────────────────────────────────────────────────────────


class TestCrear:
    def test_crear_especifica_ok(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("5000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
            observaciones="pago factura",
            creado_por_id=active_user.id,
        )
        assert op.id is not None
        assert op.estado == "pendiente"
        assert op.numero.startswith("OP-01-")

    def test_crear_especifica_suma_distinta_raise_400(
        self, db, empresa, proveedor, pedido_aprobado, active_user
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("5000"),
                modo_imputacion="especifica",
                items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("3000")}],
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_crear_a_cuenta_items_vacio_ok(self, db, empresa, proveedor, active_user) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        assert op.modo_imputacion == "a_cuenta"

    def test_crear_a_cuenta_con_items_raise_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("1000"),
                modo_imputacion="a_cuenta",
                items=[{"tipo": "saldo", "id": None, "monto": Decimal("1000")}],
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_crear_mixta_suma_menor_ok(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("6000"),
            modo_imputacion="mixta",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
            creado_por_id=active_user.id,
        )
        assert op.modo_imputacion == "mixta"

    def test_crear_monto_cero_raise_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("0"),
                modo_imputacion="a_cuenta",
                items=[],
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_crear_combo_invalido_raise_400(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("100"),
                modo_imputacion="especifica",
                items=[{"tipo": "otro_destino_raro", "id": 1, "monto": Decimal("100")}],
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# detectar_duplicado_erp + confirmar_duplicado
# ──────────────────────────────────────────────────────────────────────────


class TestDetectarDuplicadoErp:
    def test_sin_supp_id_retorna_lista_vacia(self, db, empresa, active_user) -> None:
        prov = Proveedor(id=99, nombre="Sin ERP", activo=True, origen=OrigenProveedor.MANUAL.value, supp_id=None)
        db.add(prov)
        db.flush()

        resultado = ordenes_pago_service.detectar_duplicado_erp(db, proveedor_id=prov.id, numeros_factura=["FA-001"])
        assert resultado == []

    def test_sin_numeros_factura_retorna_lista_vacia(self, db, proveedor) -> None:
        resultado = ordenes_pago_service.detectar_duplicado_erp(db, proveedor_id=proveedor.id, numeros_factura=[])
        assert resultado == []

    def test_tabla_ct_inexistente_retorna_lista_vacia(self, db, proveedor) -> None:
        """En tests no existe tb_commercial_transactions → query falla gracefully."""
        resultado = ordenes_pago_service.detectar_duplicado_erp(
            db, proveedor_id=proveedor.id, numeros_factura=["FA-123"]
        )
        assert resultado == []

    def test_crear_con_flag_confirmar_registra_evento(
        self, db, empresa, proveedor, pedido_aprobado, active_user
    ) -> None:
        """Si detectar_duplicado_erp retorna duplicados y confirmar_duplicado=True → OK + evento."""
        duplicados_fake = [
            {
                "ct_transaction": 768710,
                "ct_date": "2026-04-15",
                "ct_docnumber": "FA-12345",
                "ct_total": "19420875.00",
            }
        ]
        with patch(
            "app.services.ordenes_pago_service.detectar_duplicado_erp",
            return_value=duplicados_fake,
        ):
            op = ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("5000"),
                modo_imputacion="especifica",
                items=[
                    {
                        "tipo": "pedido_compra",
                        "id": pedido_aprobado.id,
                        "monto": Decimal("5000"),
                        "numero_factura": "FA-12345",
                    }
                ],
                creado_por_id=active_user.id,
                confirmar_duplicado=True,
            )
            assert op.id is not None

            eventos = (
                db.query(CompraEvento)
                .filter(
                    CompraEvento.entidad_id == op.id,
                    CompraEvento.tipo == "op_creada_con_duplicado_confirmado",
                )
                .all()
            )
            assert len(eventos) == 1
            assert 768710 in eventos[0].payload["ct_transaction_duplicada"]

    def test_crear_con_duplicado_sin_confirmar_raise_409(
        self, db, empresa, proveedor, pedido_aprobado, active_user
    ) -> None:
        duplicados_fake = [{"ct_transaction": 1, "ct_date": "2026-04-15", "ct_docnumber": "FA-1", "ct_total": "100"}]
        with patch(
            "app.services.ordenes_pago_service.detectar_duplicado_erp",
            return_value=duplicados_fake,
        ):
            with pytest.raises(HTTPException) as exc:
                ordenes_pago_service.crear(
                    db,
                    proveedor_id=proveedor.id,
                    empresa_id=empresa.id,
                    moneda="ARS",
                    monto_total=Decimal("5000"),
                    modo_imputacion="especifica",
                    items=[
                        {
                            "tipo": "pedido_compra",
                            "id": pedido_aprobado.id,
                            "monto": Decimal("5000"),
                            "numero_factura": "FA-1",
                        }
                    ],
                    creado_por_id=active_user.id,
                    confirmar_duplicado=False,
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["codigo"] == "POSIBLE_DUPLICADO_OP_ERP"


# ──────────────────────────────────────────────────────────────────────────
# ejecutar_pago (COMPRAS-4.6) — el corazón
# ──────────────────────────────────────────────────────────────────────────


class TestEjecutarPago:
    def test_happy_path_completo(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("5000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
            creado_por_id=active_user.id,
        )

        op = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 4, 20),
            user_id=active_user.id,
        )

        assert op.estado == "pagado"
        assert op.caja_id == caja_ars.id
        assert op.caja_movimiento_id is not None
        assert op.caja_documento_id is not None
        assert op.fecha_pago_real == date(2026, 4, 20)
        assert op.paid_at is not None

        # Caja tuvo egreso
        movs = db.query(CajaMovimiento).filter(CajaMovimiento.caja_id == caja_ars.id).all()
        assert len(movs) == 1
        assert movs[0].tipo == "egreso"
        assert movs[0].monto == Decimal("5000")
        assert movs[0].origen == "orden_pago"

        # Imputación creada
        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id).all()
        assert len(imps) == 1
        assert imps[0].destino_tipo == "pedido_compra"
        assert imps[0].destino_id == pedido_aprobado.id

        # CC movimiento (haber)
        cc_movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.origen_tipo == "imputacion").all()
        assert len(cc_movs) == 1
        assert cc_movs[0].tipo == "haber"

        # Pedido pasó a 'pagado' (transición automática)
        db.refresh(pedido_aprobado)
        assert pedido_aprobado.estado == "pagado"

        # Evento op_pagada
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == "op_pagada",
            )
            .all()
        )
        assert len(eventos) == 1

    def test_caja_moneda_distinta_raise_422(
        self,
        db,
        empresa,
        proveedor,
        caja_usd,
        tipos_doc_caja,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_usd.id,
                fecha_pago_real=date(2026, 4, 20),
                user_id=active_user.id,
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["codigo"] == "OP_CAJA_MONEDA_MISMATCH"

    def test_op_ya_pagada_raise_400(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_ars.id,
                fecha_pago_real=date.today(),
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_mixta_crea_imputacion_saldo_del_remanente(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("8000"),
            modo_imputacion="mixta",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
            creado_por_id=active_user.id,
        )
        op = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        assert op.estado == "pagado"

        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id).order_by(Imputacion.id).all()
        assert len(imps) == 2
        assert imps[0].destino_tipo == "pedido_compra"
        assert imps[1].destino_tipo == "saldo"
        assert imps[1].monto_imputado == Decimal("3000")

    def test_a_cuenta_imputa_todo_a_saldo(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1500"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id).all()
        assert len(imps) == 1
        assert imps[0].destino_tipo == "saldo"
        assert imps[0].monto_imputado == Decimal("1500")


# ──────────────────────────────────────────────────────────────────────────
# anular
# ──────────────────────────────────────────────────────────────────────────


class TestAnular:
    def test_anular_op_pagada_happy_path(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("5000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )

        op = ordenes_pago_service.anular(
            db,
            orden_pago_id=op.id,
            motivo="pago duplicado",
            user_id=active_user.id,
        )
        assert op.estado == "anulado"

        # Caja: 1 egreso + 1 ingreso compensatorio
        movs = db.query(CajaMovimiento).filter(CajaMovimiento.caja_id == caja_ars.id).order_by(CajaMovimiento.id).all()
        assert len(movs) == 2
        assert movs[0].tipo == "egreso"
        assert movs[1].tipo == "ingreso"
        assert movs[1].monto == Decimal("5000")

        # Imputaciones: 1 original + 1 reversal
        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id).order_by(Imputacion.id).all()
        assert len(imps) == 2
        assert imps[0].es_reversal is False
        assert imps[1].es_reversal is True
        assert imps[1].reimputada_desde_id == imps[0].id

        # Pedido vuelve a aprobado (no queda pagado)
        db.refresh(pedido_aprobado)
        assert pedido_aprobado.estado == "aprobado"

        # Evento op_anulada
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == "op_anulada",
            )
            .all()
        )
        assert len(eventos) == 1

    def test_anular_op_no_pagada_raise_400(self, db, empresa, proveedor, tipos_doc_caja, active_user) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("100"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        # Estado pendiente
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.anular(db, orden_pago_id=op.id, motivo="foo", user_id=active_user.id)
        assert exc.value.status_code == 400

    def test_anular_sin_motivo_raise_400(self, db, empresa, proveedor, caja_ars, tipos_doc_caja, active_user) -> None:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("100"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.anular(db, orden_pago_id=op.id, motivo="   ", user_id=active_user.id)
        assert exc.value.status_code == 400
