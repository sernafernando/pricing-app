"""Unit tests for OC-match PedidoCompra documentary write-back."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.pedido_compra import CorreccionPedidoRequest, PedidoCompraUpdate
from app.services.oc_match.doc_refs import apply_writeback, normalize_tipo


def _pedido(
    *,
    facturas: str | None = None,
    pedidos: str | None = None,
    numero_factura: str | None = "ERP-KEEP",
) -> SimpleNamespace:
    return SimpleNamespace(
        facturas_documento=facturas,
        pedidos_documento=pedidos,
        numero_factura=numero_factura,
    )


class TestNormalizeTipo:
    def test_nv_alias_and_null_unknown(self) -> None:
        assert normalize_tipo("nv") == "nota_venta"
        assert normalize_tipo("Nota de venta") == "nota_venta"
        assert normalize_tipo("recibo") == "comprobante_pago"
        assert normalize_tipo(None) == "otro"
        assert normalize_tipo("desconocido") == "otro"

    def test_nc_nd_aliases(self) -> None:
        assert normalize_tipo("nc") == "nota_credito"
        assert normalize_tipo("nota de credito") == "nota_credito"
        assert normalize_tipo("nota_de_credito") == "nota_credito"
        assert normalize_tipo("nd") == "nota_debito"
        assert normalize_tipo("nota de debito") == "nota_debito"
        assert normalize_tipo("nota_de_debito") == "nota_debito"
        assert normalize_tipo("nota_credito") == "nota_credito"
        assert normalize_tipo("nota_debito") == "nota_debito"


class TestRouteWriteback:
    def test_factura_routes_both_columns(self) -> None:
        pedido = _pedido()
        wrote = apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "factura",
                "nro_documento": "0001-99",
                "nro_pedido": "PED-184465",
            },
        )
        assert wrote is True
        assert pedido.facturas_documento == "0001-99"
        assert pedido.pedidos_documento == "PED-184465"
        assert pedido.numero_factura == "ERP-KEEP"

    def test_proforma_writes_only_pedidos(self) -> None:
        pedido = _pedido(facturas="KEEP-FA")
        wrote = apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "proforma",
                "nro_documento": "0001-99",
                "nro_pedido": "PED-184465",
            },
        )
        assert wrote is True
        assert pedido.pedidos_documento == "0001-99; PED-184465"
        assert pedido.facturas_documento == "KEEP-FA"
        assert pedido.numero_factura == "ERP-KEEP"

    def test_nc_nd_skip_writeback(self) -> None:
        pedido = _pedido(facturas="A", pedidos="B")
        for tipo in ("nota_credito", "nota_debito", "nc", "nd"):
            assert (
                apply_writeback(
                    pedido,  # type: ignore[arg-type]
                    {
                        "tipo_documento": tipo,
                        "nro_documento": "NC-1",
                        "nro_pedido": "00184465",
                    },
                )
                is False
            )
        assert pedido.facturas_documento == "A"
        assert pedido.pedidos_documento == "B"

    def test_skip_comprobante_pago_and_otro(self) -> None:
        pedido = _pedido(facturas="A", pedidos="B")
        assert (
            apply_writeback(
                pedido,  # type: ignore[arg-type]
                {
                    "tipo_documento": "comprobante_pago",
                    "nro_documento": "REC-1",
                    "nro_pedido": "PED-9",
                },
            )
            is False
        )
        assert (
            apply_writeback(
                pedido,  # type: ignore[arg-type]
                {
                    "tipo_documento": "otro",
                    "nro_documento": "X",
                    "nro_pedido": "Y",
                },
            )
            is False
        )
        assert pedido.facturas_documento == "A"
        assert pedido.pedidos_documento == "B"

    def test_empty_numbers_are_false(self) -> None:
        pedido = _pedido(facturas="A")
        assert (
            apply_writeback(
                pedido,  # type: ignore[arg-type]
                {"tipo_documento": "factura", "nro_documento": "  ", "nro_pedido": None},
            )
            is False
        )
        assert pedido.facturas_documento == "A"

    def test_append_unique_casefold_then_c(self) -> None:
        pedido = _pedido(facturas="A; B")
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {"tipo_documento": "factura", "nro_documento": "a"},
        )
        assert pedido.facturas_documento == "A; B"
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {"tipo_documento": "factura", "nro_documento": "C"},
        )
        assert pedido.facturas_documento == "A; B; C"

    def test_never_writes_numero_factura(self) -> None:
        pedido = _pedido(numero_factura="FA-ERP")
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "factura",
                "nro_documento": "0001-99",
                "nro_pedido": "PED-184465",
            },
        )
        assert pedido.numero_factura == "FA-ERP"


class TestDocRefsMaxLength:
    def test_update_over_500_is_validation_error(self) -> None:
        over = "x" * 501
        with pytest.raises(ValidationError):
            PedidoCompraUpdate(facturas_documento=over)
        with pytest.raises(ValidationError):
            PedidoCompraUpdate(pedidos_documento=over)

    def test_correccion_over_500_is_validation_error(self) -> None:
        over = "x" * 501
        with pytest.raises(ValidationError):
            CorreccionPedidoRequest(motivo_correccion="motivo valido", facturas_documento=over)
        with pytest.raises(ValidationError):
            CorreccionPedidoRequest(motivo_correccion="motivo valido", pedidos_documento=over)
