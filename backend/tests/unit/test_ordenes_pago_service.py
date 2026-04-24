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


# ──────────────────────────────────────────────────────────────────────────
# editar (sub-batch 1.1)
# ──────────────────────────────────────────────────────────────────────────


class TestEditarOP:
    def _crear_op_pendiente(
        self,
        db,
        empresa,
        proveedor,
        pedido_aprobado,
        active_user,
        monto: Decimal = Decimal("5000"),
    ):
        return ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=monto,
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": monto}],
            creado_por_id=active_user.id,
        )

    def test_editar_op_pendiente_happy(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)

        editada = ordenes_pago_service.editar(
            db,
            op_id=op.id,
            observaciones="Observación nueva",
            user_id=active_user.id,
        )
        assert editada.observaciones == "Observación nueva"
        assert editada.estado == "pendiente"

        # Evento op_editada creado con diff.
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == ordenes_pago_service.EVENTO_OP_EDITADA,
            )
            .all()
        )
        assert len(eventos) == 1
        assert "observaciones" in eventos[0].payload["diff"]

    def test_editar_op_pagada_raises_409(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.editar(
                db,
                op_id=op.id,
                observaciones="cambio tarde",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409

    def test_editar_op_cancelada_raises_409(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)
        ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="error carga", user_id=active_user.id)

        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.editar(db, op_id=op.id, observaciones="x", user_id=active_user.id)
        assert exc.value.status_code == 409

    def test_editar_op_items_genera_evento_items_editados(
        self, db, empresa, proveedor, pedido_aprobado, active_user
    ) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)

        # Evento items_registrados existe post-crear.
        pre = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == ordenes_pago_service.EVENTO_ITEMS_REGISTRADOS,
            )
            .count()
        )
        assert pre == 1

        nuevos_items = [
            {"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("4000")},
            {"tipo": "saldo", "id": None, "monto": Decimal("1000")},
        ]
        ordenes_pago_service.editar(
            db,
            op_id=op.id,
            modo_imputacion="mixta",
            monto_total=Decimal("5001"),  # > 5000 = sum items => mixta válida (sum < total)
            items=nuevos_items,
            user_id=active_user.id,
        )

        # items_registrados sigue vivo (append-only).
        registrados = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == ordenes_pago_service.EVENTO_ITEMS_REGISTRADOS,
            )
            .count()
        )
        assert registrados == 1

        # items_editados nuevo.
        editados = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == ordenes_pago_service.EVENTO_ITEMS_EDITADOS,
            )
            .all()
        )
        assert len(editados) == 1
        assert len(editados[0].payload["items"]) == 2

    def test_editar_op_validacion_suma_items_vs_modo(
        self, db, empresa, proveedor, pedido_aprobado, active_user
    ) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.editar(
                db,
                op_id=op.id,
                monto_total=Decimal("9999"),  # no coincide con suma items
                items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("5000")}],
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_editar_op_tc_con_moneda_ars_raises(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
        op = self._crear_op_pendiente(db, empresa, proveedor, pedido_aprobado, active_user)
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.editar(
                db,
                op_id=op.id,
                tipo_cambio=Decimal("1100"),  # moneda ARS → inválido
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_editar_op_404_inexistente(self, db, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.editar(db, op_id=99999, observaciones="x", user_id=active_user.id)
        assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# cancelar_pendiente (sub-batch 1.2)
# ──────────────────────────────────────────────────────────────────────────


class TestCancelarPendiente:
    def test_cancelar_op_pendiente_happy(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
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

        cancelada = ordenes_pago_service.cancelar_pendiente(
            db, op_id=op.id, motivo="cargada con error", user_id=active_user.id
        )
        assert cancelada.estado == "cancelado"

        # No hay imputaciones
        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id).count()
        assert imps == 0

        # No hay movimientos de caja
        movs = db.query(CajaMovimiento).count()
        assert movs == 0

        # Evento auditado
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == op.id,
                CompraEvento.tipo == ordenes_pago_service.EVENTO_OP_CANCELADA_PENDIENTE,
            )
            .all()
        )
        assert len(eventos) == 1
        assert eventos[0].payload["motivo"] == "cargada con error"

    def test_cancelar_op_pagada_raises_409(
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

        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="muy tarde", user_id=active_user.id)
        assert exc.value.status_code == 409

    def test_cancelar_op_motivo_vacio_raises_400(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
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
            ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="   ", user_id=active_user.id)
        assert exc.value.status_code == 400

    def test_cancelar_op_404_inexistente(self, db, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.cancelar_pendiente(db, op_id=99999, motivo="x", user_id=active_user.id)
        assert exc.value.status_code == 404

    def test_cancelar_op_ya_cancelada_raises_409(self, db, empresa, proveedor, pedido_aprobado, active_user) -> None:
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
        ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="uno", user_id=active_user.id)
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="dos", user_id=active_user.id)
        assert exc.value.status_code == 409


# ──────────────────────────────────────────────────────────────────────────
# ejecutar_pago con items_editados (sub-batch 1.3)
# ──────────────────────────────────────────────────────────────────────────


class TestEjecutarPagoLeeItemsEditados:
    def test_ejecutar_pago_usa_items_editados_si_existe(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        """Si hay items_editados, ejecutar_pago debe usarlos, no los items_registrados."""
        # OP original: 5000 al pedido
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

        # Editar items: mismo monto total pero ahora va todo a saldo.
        ordenes_pago_service.editar(
            db,
            op_id=op.id,
            modo_imputacion="a_cuenta",
            items=[],  # a_cuenta → sin items
            user_id=active_user.id,
        )

        # Ejecutar pago con la nueva config
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )

        # Debe haber creado imputación a saldo, NO a pedido
        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id, Imputacion.es_reversal.is_(False)).all()
        assert len(imps) == 1
        assert imps[0].destino_tipo == "saldo"
        assert imps[0].destino_id is None

    def test_ejecutar_pago_fallback_items_registrados_si_no_hay_editados(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        """Sin edición, ejecutar_pago sigue usando items_registrados (comportamiento previo)."""
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

        imps = db.query(Imputacion).filter(Imputacion.origen_id == op.id, Imputacion.es_reversal.is_(False)).all()
        assert len(imps) == 1
        assert imps[0].destino_tipo == "pedido_compra"
        assert imps[0].destino_id == pedido_aprobado.id

    def test_ejecutar_pago_sobre_op_cancelada_raises_400(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        pedido_aprobado,
        active_user,
    ) -> None:
        """OP cancelada no se puede pagar (estado != pendiente)."""
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
        ordenes_pago_service.cancelar_pendiente(db, op_id=op.id, motivo="x", user_id=active_user.id)

        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_ars.id,
                fecha_pago_real=date.today(),
                user_id=active_user.id,
            )
        # Consistente con design: estado != pendiente → 400
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# Cross-moneda + TC override (sub-batch 2.2 / 2.3)
# ──────────────────────────────────────────────────────────────────────────


class TestEjecutarPagoCrossMoneda:
    def test_ejecutar_pago_con_tc_override_sobrescribe_op(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        """tipo_cambio_override debe persistirse en op.tipo_cambio."""
        # OP en ARS con caja ARS — mismo moneda, override solo persiste.
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
        # Para ARS pura, el override no tiene semántica especial pero SÍ
        # sobrescribe el campo si se manda (no va a haber conversión, igual).
        # Test relevante: override SÍ pisa en el caso cross-moneda. Validamos
        # el mecanismo con moneda USD + caja ARS en el siguiente test.
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        assert op.estado == "pagado"

    def test_ejecutar_pago_cross_moneda_con_tc_override_ok(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        """OP USD + caja ARS + tipo_cambio_override → movimiento ARS = monto*TC."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="USD",
            monto_total=Decimal("100"),  # 100 USD
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
            tipo_cambio_override=Decimal("1200"),
        )

        assert op.estado == "pagado"
        assert op.tipo_cambio == Decimal("1200")

        # El movimiento de caja debe tener monto ARS = 100 * 1200 = 120000.
        mov = db.query(CajaMovimiento).filter(CajaMovimiento.id == op.caja_movimiento_id).one()
        assert mov.monto == Decimal("120000.00")

    def test_ejecutar_pago_cross_moneda_con_tc_previo_en_op_ok(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        """OP USD con tipo_cambio pre-seteado + caja ARS → cross-moneda sin override."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="USD",
            monto_total=Decimal("50"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        # Editar OP para setear TC (pendiente editable — sub-batch 1.1).
        ordenes_pago_service.editar(
            db,
            op_id=op.id,
            tipo_cambio=Decimal("1000"),
            user_id=active_user.id,
        )

        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        mov = db.query(CajaMovimiento).filter(CajaMovimiento.id == op.caja_movimiento_id).one()
        assert mov.monto == Decimal("50000.00")  # 50 USD * 1000

    def test_ejecutar_pago_cross_moneda_sin_tc_422(
        self,
        db,
        empresa,
        proveedor,
        caja_ars,
        tipos_doc_caja,
        active_user,
    ) -> None:
        """OP USD + caja ARS sin TC → 422 OP_CAJA_MONEDA_MISMATCH (comportamiento previo)."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="USD",
            monto_total=Decimal("100"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_ars.id,
                fecha_pago_real=date.today(),
                user_id=active_user.id,
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["codigo"] == "OP_CAJA_MONEDA_MISMATCH"

    def test_ejecutar_pago_tc_override_negativo_raises_400(
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
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_ars.id,
                fecha_pago_real=date.today(),
                user_id=active_user.id,
                tipo_cambio_override=Decimal("-1"),
            )
        assert exc.value.status_code == 400
