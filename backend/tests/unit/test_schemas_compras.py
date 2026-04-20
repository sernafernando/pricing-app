"""
Unit tests para schemas Pydantic v2 del módulo compras.

Smoke tests: un payload válido parsea; uno inválido levanta
`ValidationError`. No intenta cubrir todas las ramas — eso lo hacen los
tests de los endpoints en Fase 5.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.cc_proveedor import CCMovimientoResponse, SaldoPorMoneda
from app.schemas.compra_evento import CompraEventoResponse
from app.schemas.imputacion import ImputacionDesimputar, ImputacionReimputar
from app.schemas.orden_pago import (
    DuplicadoOPERPInfo,
    ImputacionItem,
    OrdenPagoCreate,
    OrdenPagoEjecutarPago,
    PosibleDuplicadoResponse,
)
from app.schemas.pedido_compra import PedidoCompraCreate, PedidoCompraUpdate
from app.schemas.sale_document import SaleDocumentResponse


# ---------------------------------------------------------------------------
# PedidoCompra
# ---------------------------------------------------------------------------


class TestPedidoCompraCreate:
    """Smoke tests de validación del input POST /pedidos."""

    def test_payload_minimo_valido_parsea(self) -> None:
        pc = PedidoCompraCreate(
            empresa_id=1,
            proveedor_id=10,
            moneda="ARS",
            monto=Decimal("1500.00"),
        )
        assert pc.moneda == "ARS"
        assert pc.monto == Decimal("1500.00")
        assert pc.requiere_envio is False  # default

    def test_moneda_invalida_raises(self) -> None:
        with pytest.raises(ValidationError):
            PedidoCompraCreate(
                empresa_id=1,
                proveedor_id=10,
                moneda="EUR",
                monto=Decimal("100.00"),
            )

    def test_monto_no_positivo_raises(self) -> None:
        with pytest.raises(ValidationError):
            PedidoCompraCreate(
                empresa_id=1,
                proveedor_id=10,
                moneda="USD",
                monto=Decimal("0"),
            )

    def test_update_todos_opcionales(self) -> None:
        pu = PedidoCompraUpdate()
        dumped = pu.model_dump(exclude_unset=True)
        assert dumped == {}


# ---------------------------------------------------------------------------
# OrdenPago
# ---------------------------------------------------------------------------


class TestOrdenPagoCreate:
    """Smoke tests del body de creación de OP."""

    def test_op_con_items_parsea(self) -> None:
        op = OrdenPagoCreate(
            empresa_id=1,
            proveedor_id=10,
            moneda="ARS",
            monto_total=Decimal("5000.00"),
            modo_imputacion="especifica",
            items=[
                ImputacionItem(tipo="pedido_compra", id=42, monto=Decimal("3000.00")),
                ImputacionItem(tipo="saldo", monto=Decimal("2000.00")),
            ],
            confirmar_duplicado=False,
        )
        assert len(op.items) == 2
        assert op.items[1].tipo == "saldo"
        assert op.items[1].id is None  # saldo no requiere id
        assert op.confirmar_duplicado is False

    def test_modo_imputacion_invalido_raises(self) -> None:
        with pytest.raises(ValidationError):
            OrdenPagoCreate(
                empresa_id=1,
                proveedor_id=10,
                moneda="ARS",
                monto_total=Decimal("100.00"),
                modo_imputacion="otra_cosa",
            )

    def test_ejecutar_pago_requiere_caja_y_fecha(self) -> None:
        ep = OrdenPagoEjecutarPago(caja_id=7, fecha_pago_real=date(2026, 4, 17))
        assert ep.caja_id == 7

        with pytest.raises(ValidationError):
            OrdenPagoEjecutarPago(caja_id=7)  # type: ignore[call-arg]


class TestPosibleDuplicadoResponse:
    """Envelope del HTTP 409 POSIBLE_DUPLICADO_OP_ERP."""

    def test_envelope_con_defaults(self) -> None:
        dup = DuplicadoOPERPInfo(
            ct_transaction=123456789,
            ct_date=datetime(2026, 4, 10, 15, 30, tzinfo=timezone.utc),
            ct_docnumber="0001-00012345",
            ct_total=Decimal("5000.00"),
        )
        resp = PosibleDuplicadoResponse(
            mensaje="Ya existe una OP similar en el ERP",
            duplicados=[dup],
        )
        assert resp.codigo == "POSIBLE_DUPLICADO_OP_ERP"
        assert resp.flag_confirmacion == "confirmar_duplicado"
        assert len(resp.duplicados) == 1
        assert resp.duplicados[0].ct_transaction == 123456789


# ---------------------------------------------------------------------------
# Imputacion
# ---------------------------------------------------------------------------


class TestImputacionBodies:
    """Bodies de desimputar / reimputar."""

    def test_desimputar_con_motivo_valido(self) -> None:
        body = ImputacionDesimputar(motivo="Error de carga — destino equivocado")
        assert "equivocado" in body.motivo

    def test_desimputar_sin_motivo_raises(self) -> None:
        with pytest.raises(ValidationError):
            ImputacionDesimputar(motivo="")

    def test_reimputar_a_saldo_sin_destino_id(self) -> None:
        body = ImputacionReimputar(
            destino_tipo="saldo",
            motivo="Reasigno a saldo a cuenta del proveedor",
        )
        assert body.destino_id is None


# ---------------------------------------------------------------------------
# CC Proveedor
# ---------------------------------------------------------------------------


class TestCCProveedor:
    def test_saldo_por_moneda_basico(self) -> None:
        s = SaldoPorMoneda(moneda="USD", saldo=Decimal("1234.56"), movimientos_count=10)
        assert s.saldo == Decimal("1234.56")

    def test_movimiento_con_from_attributes(self) -> None:
        """Valida que `from_attributes=True` permite construir desde un objeto simulado."""

        class FakeMov:
            id = 1
            proveedor_id = 10
            empresa_id = 1
            fecha_movimiento = date(2026, 4, 10)
            tipo = "debe"
            signo_ajuste = None
            monto = Decimal("500.00")
            moneda = "ARS"
            tipo_cambio_a_ars = None
            origen_tipo = "pedido_compra"
            origen_id = 42
            descripcion = "Test"
            creado_por_id = 1
            created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)

        mov = CCMovimientoResponse.model_validate(FakeMov())
        assert mov.tipo == "debe"
        assert mov.proveedor_id == 10


# ---------------------------------------------------------------------------
# SaleDocument
# ---------------------------------------------------------------------------


class TestSaleDocumentResponse:
    def test_parsea_payload_catalogo(self) -> None:
        sd = SaleDocumentResponse(
            sd_id=1,
            sd_desc="Factura A",
            sd_iscredit=False,
            sd_isquotation=False,
            sd_isreceipt=False,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_issales=True,
            sd_ispurchase=False,
            sd_isbanking=False,
            sd_ispackinglist=False,
            sd_iscreditnote=False,
            sd_isdebitnote=False,
            sd_isannulment=False,
            sd_plusorminus=1,
            hacc_group=10101,
            clasificacion="FACTURA",
        )
        assert sd.clasificacion == "FACTURA"


# ---------------------------------------------------------------------------
# CompraEvento
# ---------------------------------------------------------------------------


class TestCompraEventoResponse:
    def test_parsea_evento_con_payload_arbitrario(self) -> None:
        ev = CompraEventoResponse(
            id=1,
            entidad_tipo="pedido_compra",
            entidad_id=42,
            tipo="aprobado",
            usuario_id=5,
            payload={"nota": "OK", "monto_aprobado": "1500.00"},
            created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
        )
        assert ev.payload["nota"] == "OK"

    def test_entidad_tipo_invalida_raises(self) -> None:
        with pytest.raises(ValidationError):
            CompraEventoResponse(
                id=1,
                entidad_tipo="factura",  # no permitido
                entidad_id=42,
                tipo="algo",
                usuario_id=5,
                payload=None,
                created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
            )
