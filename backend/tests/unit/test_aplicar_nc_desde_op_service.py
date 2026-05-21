"""
T4.3–T4.8 — Tests unitarios para F4: aplicar_nc_desde_op service.

Cubre:
  - AC4.1: happy path OP con un solo pedido → imputación creada.
  - AC4.2: monto > saldo disponible de la NC → 422.
  - AC4.3: NC pertenece a proveedor distinto → 403.
  - AC4.4: NC completamente consumida → 409.
  - AC4.5a: OP con múltiples pedidos, sin pedido_id → 422 con lista de opciones.
  - AC4.5b: OP con múltiples pedidos, con pedido_id → éxito.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=10, nombre="EmpresaF4", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=10,
        nombre="ProveedorF4",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=99,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def proveedor_otro(db) -> Proveedor:
    """Proveedor distinto — para test de ownership (AC4.3)."""
    p = Proveedor(
        id=11,
        nombre="OtroProveedor",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=100,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=10,
        numero="PC-10-2026-00001",
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
def pedido2(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Segundo pedido del mismo proveedor — para test multi-pedido (AC4.5)."""
    p = PedidoCompra(
        id=11,
        numero="PC-10-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("15000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def op(db, empresa, proveedor, active_user) -> OrdenPago:
    """OP pagada asociada al proveedor."""
    o = OrdenPago(
        id=10,
        numero="OP-10-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("15000"),
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=False,
        creado_por_id=active_user.id,
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def imputacion_op_pedido(db, op, pedido, proveedor, active_user) -> Imputacion:
    """Imputación existente OP→pedido (la OP ya pagó contra ese pedido)."""
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=Decimal("15000"),
        moneda_imputada="ARS",
        proveedor_id=proveedor.id,
        es_reversal=False,
        creado_por_id=active_user.id,
    )
    db.add(imp)
    db.flush()
    return imp


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    """NC local aprobada del mismo proveedor, ARS 10 000."""
    nc = NotaCreditoLocal(
        id=10,
        numero="NC-10-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Ajuste por devolucion",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


@pytest.fixture
def nc_otro_proveedor(db, empresa, proveedor_otro, active_user) -> NotaCreditoLocal:
    """NC de otro proveedor."""
    nc = NotaCreditoLocal(
        id=11,
        numero="NC-11-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor_otro.id,
        moneda="ARS",
        monto=Decimal("5000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Ajuste externo",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


@pytest.fixture
def nc_aplicada_parcial(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    """NC en estado 'aplicada_parcial' — ya aplicada pero aún con saldo disponible."""
    nc = NotaCreditoLocal(
        id=13,
        numero="NC-10-2026-00003",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("8000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Parcialmente aplicada",
        estado="aplicada_parcial",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


@pytest.fixture
def pedido_usd(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Pedido en USD del mismo proveedor — para test cross-moneda."""
    p = PedidoCompra(
        id=12,
        numero="PC-10-2026-00003",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("500"),
        tipo_cambio=Decimal("1400"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_consumida(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    """NC ya completamente consumida (estado 'aplicada')."""
    nc = NotaCreditoLocal(
        id=12,
        numero="NC-10-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Consumida por completo",
        estado="aplicada",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarNCDesdeOP:
    """T4.3–T4.8 — Service aplicar_nc_desde_op."""

    def test_happy_path_single_pedido(self, db, op, pedido, nc_aprobada, imputacion_op_pedido, active_user) -> None:
        """T4.3 / AC4.1 — OP con un pedido, nc_id + monto válidos → imputación creada."""
        result = ordenes_pago_service.aplicar_nc_desde_op(
            db,
            op_id=op.id,
            nc_id=nc_aprobada.id,
            monto=Decimal("8000"),
            pedido_id=None,
            creado_por_id=active_user.id,
        )
        assert "imputacion_id" in result
        assert "nc_estado" in result
        imp = db.get(Imputacion, result["imputacion_id"])
        assert imp is not None
        assert imp.origen_tipo == "nota_credito_local"
        assert imp.origen_id == nc_aprobada.id
        assert imp.destino_tipo == "pedido_compra"
        assert imp.destino_id == pedido.id
        assert imp.monto_imputado == Decimal("8000")

    def test_monto_exceeds_balance_422(self, db, op, pedido, nc_aprobada, imputacion_op_pedido, active_user) -> None:
        """T4.4 / AC4.2 — monto > saldo NC → 422."""
        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_aprobada.id,
                monto=Decimal("99999"),
                pedido_id=None,
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_wrong_proveedor_403(
        self,
        db,
        op,
        pedido,
        nc_otro_proveedor,
        imputacion_op_pedido,
        active_user,
    ) -> None:
        """T4.5 / AC4.3 — NC de otro proveedor → 403."""
        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_otro_proveedor.id,
                monto=Decimal("1000"),
                pedido_id=None,
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 403

    def test_fully_consumed_nc_409(
        self,
        db,
        op,
        pedido,
        nc_consumida,
        imputacion_op_pedido,
        active_user,
    ) -> None:
        """T4.6 / AC4.4 — NC en estado 'aplicada' (consumida) → 409."""
        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_consumida.id,
                monto=Decimal("1000"),
                pedido_id=None,
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 409

    def test_multi_pedido_no_pedido_id_422(
        self,
        db,
        op,
        pedido,
        pedido2,
        nc_aprobada,
        imputacion_op_pedido,
        active_user,
    ) -> None:
        """T4.7 / AC4.5 — OP con 2 pedidos, sin pedido_id → 422 con lista."""
        # Agregar segunda imputación OP→pedido2
        imp2 = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido2.id,
            monto_imputado=Decimal("5000"),
            moneda_imputada="ARS",
            proveedor_id=pedido2.proveedor_id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp2)
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_aprobada.id,
                monto=Decimal("1000"),
                pedido_id=None,
                creado_por_id=active_user.id,
            )
        exc = exc_info.value
        assert exc.status_code == 422
        # El detail debe incluir los pedido_ids como referencia.
        detail_str = str(exc.detail)
        assert str(pedido.id) in detail_str or str(pedido2.id) in detail_str

    def test_multi_pedido_with_pedido_id_ok(
        self,
        db,
        op,
        pedido,
        pedido2,
        nc_aprobada,
        imputacion_op_pedido,
        active_user,
    ) -> None:
        """T4.8 / AC4.5 — OP con 2 pedidos, pedido_id explícito → éxito."""
        imp2 = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido2.id,
            monto_imputado=Decimal("5000"),
            moneda_imputada="ARS",
            proveedor_id=pedido2.proveedor_id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp2)
        db.flush()

        result = ordenes_pago_service.aplicar_nc_desde_op(
            db,
            op_id=op.id,
            nc_id=nc_aprobada.id,
            monto=Decimal("2000"),
            pedido_id=pedido.id,
            creado_por_id=active_user.id,
        )
        assert "imputacion_id" in result
        imp = db.get(Imputacion, result["imputacion_id"])
        assert imp.destino_id == pedido.id

    # ── Nuevos tests de refuerzo (test reinforcement pass) ──────────────────

    def test_haber_en_cc_proveedor(self, db, op, pedido, nc_aprobada, imputacion_op_pedido, active_user) -> None:
        """Aplicar NC crea un movimiento HABER en la CC del proveedor con el monto correcto.

        Éste es el efecto más crítico en términos financieros: si el HABER no
        se registra, la deuda con el proveedor queda inflada silenciosamente.
        """
        monto_aplicar = Decimal("5000")

        movimientos_antes = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == op.proveedor_id,
                CCProveedorMovimiento.tipo == "haber",
            )
            .count()
        )

        result = ordenes_pago_service.aplicar_nc_desde_op(
            db,
            op_id=op.id,
            nc_id=nc_aprobada.id,
            monto=monto_aplicar,
            pedido_id=None,
            creado_por_id=active_user.id,
        )

        movimientos_haber = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == op.proveedor_id,
                CCProveedorMovimiento.tipo == "haber",
            )
            .all()
        )

        # Al menos un HABER nuevo debe haberse creado
        assert len(movimientos_haber) > movimientos_antes, "aplicar_nc_desde_op debe emitir un HABER en CC proveedor"

        # El HABER más reciente debe corresponder a la imputación creada
        imp = db.get(Imputacion, result["imputacion_id"])
        mov_nc = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "imputacion",
                CCProveedorMovimiento.origen_id == imp.id,
            )
            .one_or_none()
        )
        assert mov_nc is not None, "Debe existir un CCProveedorMovimiento originado en la imputación NC"
        assert mov_nc.tipo == "haber", f"El movimiento debe ser HABER, pero es '{mov_nc.tipo}'"
        assert mov_nc.monto == monto_aplicar, f"El monto del HABER debe ser {monto_aplicar}, pero es {mov_nc.monto}"

    def test_cross_moneda_nc_vs_pedido_422(self, db, op, pedido_usd, nc_aprobada, active_user) -> None:
        """NC ARS contra pedido USD → 422 (cross-moneda prohibido en v1, D3).

        La OP debe tener una imputación al pedido_usd para que llegue a la
        validación de moneda (AC4.5 se resuelve antes).
        """
        # Crear imputación OP→pedido_usd para que el pedido_usd esté "en la OP"
        imp_op_usd = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido_usd.id,
            monto_imputado=Decimal("700000"),  # 500 USD × 1400
            moneda_imputada="ARS",
            proveedor_id=op.proveedor_id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp_op_usd)
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_aprobada.id,  # ARS
                monto=Decimal("1000"),
                pedido_id=pedido_usd.id,  # USD
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        assert "moneda" in exc_info.value.detail.lower() or "cross" in exc_info.value.detail.lower()

    def test_pedido_id_no_en_op_422(
        self, db, op, pedido, pedido2, nc_aprobada, imputacion_op_pedido, active_user
    ) -> None:
        """pedido_id apunta a un pedido que NO está en las imputaciones de la OP → 422.

        pedido2 nunca fue imputado a esta OP, así que especificar pedido2 como
        destino debe ser rechazado explícitamente.
        """
        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.aplicar_nc_desde_op(
                db,
                op_id=op.id,
                nc_id=nc_aprobada.id,
                monto=Decimal("1000"),
                pedido_id=pedido2.id,  # pedido2 no está imputado en esta OP
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert str(pedido2.id) in str(detail) or "no está" in str(detail)

    def test_nc_aplicada_parcial_es_aplicable(
        self, db, op, pedido, nc_aplicada_parcial, imputacion_op_pedido, active_user
    ) -> None:
        """NC en estado 'aplicada_parcial' debe poder aplicarse (tiene saldo disponible).

        El estado 'aplicada_parcial' significa que la NC fue usada antes pero
        no por completo. Debe ser aceptada por el validador de estado (AC4.4
        solo rechaza 'aplicada' con 409 y otros estados con 422).
        """
        result = ordenes_pago_service.aplicar_nc_desde_op(
            db,
            op_id=op.id,
            nc_id=nc_aplicada_parcial.id,
            monto=Decimal("3000"),  # menor que los 8000 de la NC parcial
            pedido_id=None,
            creado_por_id=active_user.id,
        )
        assert "imputacion_id" in result
        imp = db.get(Imputacion, result["imputacion_id"])
        assert imp is not None
        assert imp.origen_id == nc_aplicada_parcial.id
        assert imp.monto_imputado == Decimal("3000")
