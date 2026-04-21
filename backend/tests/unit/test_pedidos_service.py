"""
Tests de `pedidos_service` (COMPRAS-4.1 + COMPRAS-4.8 + COMPRAS-4.9).

Cubre:
  - `crear_pedido`: estado 'borrador', evento `creado`, numeración.
  - `editar_pedido`: campos editables por estado, evento `editado`,
    auto-match forward al cambiar `numero_factura`.
  - `transicionar`: matriz de transiciones válidas + inválidas (400).
  - Side effects CC al aprobar / cancelar_aprobado.
  - `aplicar_imputacion_a_pedido`: transiciones automáticas
    (aprobado → pagado_parcial → pagado).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import pedidos_service


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Pedidos Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Proveedor Pedidos", activo=True, origen=OrigenProveedor.ERP.value, supp_id=100)
    db.add(prov)
    db.flush()
    return prov


# ──────────────────────────────────────────────────────────────────────────
# crear_pedido
# ──────────────────────────────────────────────────────────────────────────


class TestCrearPedido:
    def test_crear_en_estado_borrador(self, db, empresa, proveedor, active_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("10000.00"),
            creado_por_id=active_user.id,
        )
        assert pedido.id is not None
        assert pedido.estado == "borrador"
        assert pedido.numero.startswith("P-01-")
        assert pedido.moneda == "ARS"
        assert pedido.monto == Decimal("10000.00")

    def test_crear_registra_evento_creado(self, db, empresa, proveedor, active_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            creado_por_id=active_user.id,
        )
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "creado",
            )
            .all()
        )
        assert len(eventos) == 1
        assert eventos[0].payload["numero"] == pedido.numero

    def test_crear_con_monto_cero_raise_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            pedidos_service.crear_pedido(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("0"),
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# tipo_cambio (Batch B del plan UX de compras)
# ──────────────────────────────────────────────────────────────────────────


class TestTipoCambioEnPedido:
    """Validaciones de `tipo_cambio` al crear/editar pedidos."""

    def test_crear_pedido_ars_sin_tc_ok(self, db, empresa, proveedor, active_user) -> None:
        """ARS + tipo_cambio=None → se crea con tipo_cambio=None."""
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )
        assert p.tipo_cambio is None

    def test_crear_pedido_usd_con_tc_explicito_ok(self, db, empresa, proveedor, active_user) -> None:
        """USD + tipo_cambio=1150.50 → se guarda tal cual."""
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
            tipo_cambio=Decimal("1150.50"),
        )
        assert p.tipo_cambio == Decimal("1150.50")

    def test_crear_pedido_ars_con_tc_raises_400(self, db, empresa, proveedor, active_user) -> None:
        """ARS + tipo_cambio!=None → HTTP 400."""
        with pytest.raises(HTTPException) as exc:
            pedidos_service.crear_pedido(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("100"),
                creado_por_id=active_user.id,
                tipo_cambio=Decimal("1000"),
            )
        assert exc.value.status_code == 400
        assert "tipo_cambio" in exc.value.detail.lower()

    def test_crear_pedido_usd_tc_invalido_raises_400(self, db, empresa, proveedor, active_user) -> None:
        """USD + tipo_cambio<=0 → HTTP 400."""
        with pytest.raises(HTTPException) as exc:
            pedidos_service.crear_pedido(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="USD",
                monto=Decimal("100"),
                creado_por_id=active_user.id,
                tipo_cambio=Decimal("0"),
            )
        assert exc.value.status_code == 400

    def test_crear_pedido_usd_sin_tc_intenta_leer_del_dia(self, db, empresa, proveedor, active_user) -> None:
        """USD + tipo_cambio=None → el servicio intenta leer el TC del día.

        Sin fila en `tipo_cambio` para hoy → queda None con log WARNING.
        Con fila presente → el valor se auto-llena.
        """
        from datetime import date as date_cls

        from app.models.tipo_cambio import TipoCambio

        # Sin TC en DB → tipo_cambio del pedido queda None.
        p1 = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("50"),
            creado_por_id=active_user.id,
        )
        assert p1.tipo_cambio is None

        # Insertamos TC del día.
        tc = TipoCambio(
            fecha=date_cls.today(),
            moneda="USD",
            compra=1100.0,
            venta=1150.0,
        )
        db.add(tc)
        db.flush()

        p2 = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("75"),
            creado_por_id=active_user.id,
        )
        # Se usa el `venta` (lo que paga el usuario).
        assert p2.tipo_cambio == Decimal("1150.0") or p2.tipo_cambio == Decimal("1150")

    def test_editar_pedido_cambia_moneda_ars_a_usd_intenta_autocompletar_tc(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """Al pasar un pedido borrador de ARS→USD sin TC explícito, intenta autocompletar."""
        from datetime import date as date_cls

        from app.models.tipo_cambio import TipoCambio

        db.add(TipoCambio(fecha=date_cls.today(), moneda="USD", compra=1200.0, venta=1250.0))
        db.flush()

        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        assert p.tipo_cambio is None

        pedidos_service.editar_pedido(
            db,
            pedido_id=p.id,
            user_id=active_user.id,
            moneda="USD",
        )
        db.refresh(p)
        assert p.moneda == "USD"
        # Autollenó con venta del día.
        assert p.tipo_cambio in (Decimal("1250.0"), Decimal("1250"))


# ──────────────────────────────────────────────────────────────────────────
# editar_pedido
# ──────────────────────────────────────────────────────────────────────────


class TestEditarPedido:
    def test_editar_en_borrador_todos_los_campos(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        pedidos_service.editar_pedido(
            db,
            pedido_id=p.id,
            user_id=active_user.id,
            monto=Decimal("999.99"),
            fecha_pago_texto="mes que viene",
            requiere_envio=True,
        )
        db.refresh(p)
        assert p.monto == Decimal("999.99")
        assert p.fecha_pago_texto == "mes que viene"
        assert p.requiere_envio is True

    def test_editar_registra_evento_con_diff(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        pedidos_service.editar_pedido(db, pedido_id=p.id, user_id=active_user.id, monto=Decimal("200"))

        evento_editado = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == p.id,
                CompraEvento.tipo == "editado",
            )
            .one()
        )
        campos = evento_editado.payload["campos_cambiados"]
        assert "monto" in campos
        assert campos["monto"]["antes"] == "100"
        assert campos["monto"]["despues"] == "200"

    def test_editar_en_aprobado_solo_numero_factura(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        p.estado = "aprobado"
        db.flush()

        # numero_factura: permitido
        pedidos_service.editar_pedido(
            db,
            pedido_id=p.id,
            user_id=active_user.id,
            numero_factura="FA-12345",
        )
        db.refresh(p)
        assert p.numero_factura == "FA-12345"

    def test_editar_monto_en_aprobado_raise_409(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        p.estado = "aprobado"
        db.flush()

        with pytest.raises(HTTPException) as exc:
            pedidos_service.editar_pedido(
                db,
                pedido_id=p.id,
                user_id=active_user.id,
                monto=Decimal("200"),
            )
        assert exc.value.status_code == 409

    def test_editar_en_pagado_raise_409(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        p.estado = "pagado"
        db.flush()

        with pytest.raises(HTTPException) as exc:
            pedidos_service.editar_pedido(
                db,
                pedido_id=p.id,
                user_id=active_user.id,
                numero_factura="FA-1",
            )
        assert exc.value.status_code == 409

    def test_editar_numero_factura_invoca_match_forward(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        p.estado = "aprobado"
        db.flush()

        with patch("app.services.pedidos_service.erp_matching_service.match_forward") as mock_mf:
            mock_mf.return_value = None
            pedidos_service.editar_pedido(
                db,
                pedido_id=p.id,
                user_id=active_user.id,
                numero_factura="FA-NUEVA",
            )
            mock_mf.assert_called_once()
            kwargs = mock_mf.call_args.kwargs
            assert kwargs["pedido_compra_id"] == p.id


# ──────────────────────────────────────────────────────────────────────────
# transicionar — matriz
# ──────────────────────────────────────────────────────────────────────────


class TestTransicionar:
    def test_borrador_a_pendiente_aprobacion(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(
            db,
            pedido_id=p.id,
            accion="enviar_aprobacion",
            user_id=active_user.id,
        )
        db.refresh(p)
        assert p.estado == "pendiente_aprobacion"

    def test_borrador_a_aprobado_salto_ilegal_raise_400(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc:
            pedidos_service.transicionar(
                db,
                pedido_id=p.id,
                accion="aprobar",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "no permitida" in exc.value.detail.lower()

    def test_aprobar_inserta_debe_en_cc(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000.00"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(
            db,
            pedido_id=p.id,
            accion="aprobar",
            user_id=active_user.id,
            fecha_pago_estimada=date(2026, 5, 1),
        )
        db.refresh(p)
        assert p.estado == "aprobado"
        assert p.aprobado_por_id == active_user.id
        assert p.fecha_pago_estimada == date(2026, 5, 1)

        movs = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "pedido_compra",
                CCProveedorMovimiento.origen_id == p.id,
            )
            .all()
        )
        assert len(movs) == 1
        assert movs[0].tipo == "debe"
        assert movs[0].monto == Decimal("5000.00")

    def test_cancelar_aprobado_inserta_ajuste_reverso(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("3000"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)
        pedidos_service.transicionar(
            db,
            pedido_id=p.id,
            accion="cancelar_aprobado",
            user_id=active_user.id,
            motivo="proveedor canceló",
        )
        db.refresh(p)
        assert p.estado == "cancelado"

        movs = (
            db.query(CCProveedorMovimiento)
            .filter(CCProveedorMovimiento.origen_id == p.id)
            .order_by(CCProveedorMovimiento.id.asc())
            .all()
        )
        assert len(movs) == 2
        assert movs[0].tipo == "debe"
        assert movs[1].tipo == "ajuste"
        assert movs[1].signo_ajuste == -1

    def test_todas_las_transiciones_registran_evento(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(
            db,
            pedido_id=p.id,
            accion="rechazar_devolver",
            user_id=active_user.id,
            motivo="falta info",
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="reabrir", user_id=active_user.id)

        eventos = db.query(CompraEvento).filter(CompraEvento.entidad_id == p.id).order_by(CompraEvento.id.asc()).all()
        tipos = [e.tipo for e in eventos]
        # creado + enviado_aprobacion + rechazado + reabierto
        assert "creado" in tipos
        assert "enviado_aprobacion" in tipos
        assert "rechazado" in tipos
        assert "reabierto" in tipos


# ──────────────────────────────────────────────────────────────────────────
# aplicar_imputacion_a_pedido — transiciones automáticas
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarImputacionAPedido:
    def test_aprobado_con_imputacion_parcial_pasa_a_pagado_parcial(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)

        # Simular imputación parcial
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=9999,
            destino_tipo="pedido_compra",
            destino_id=p.id,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        pedidos_service.aplicar_imputacion_a_pedido(db, pedido_id=p.id, monto_imputado=Decimal("400"))
        db.refresh(p)
        assert p.estado == "pagado_parcial"

    def test_aprobado_con_imputacion_total_pasa_a_pagado(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)

        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=9999,
            destino_tipo="pedido_compra",
            destino_id=p.id,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        pedidos_service.aplicar_imputacion_a_pedido(db, pedido_id=p.id, monto_imputado=Decimal("1000"))
        db.refresh(p)
        assert p.estado == "pagado"
