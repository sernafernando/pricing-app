"""Unit tests for OC-match PedidoCompra documentary write-back."""

from __future__ import annotations

from types import SimpleNamespace

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


class TestRouteWriteback:
    def test_factura_routes_both_columns(self) -> None:
        pedido = _pedido()
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "factura",
                "nro_documento": "0001-99",
                "nro_pedido": "PED-184465",
            },
        )
        assert pedido.facturas_documento == "0001-99"
        assert pedido.pedidos_documento == "PED-184465"
        assert pedido.numero_factura == "ERP-KEEP"

    def test_proforma_writes_only_pedidos(self) -> None:
        pedido = _pedido(facturas="KEEP-FA")
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "proforma",
                "nro_documento": "0001-99",
                "nro_pedido": "PED-184465",
            },
        )
        assert pedido.pedidos_documento == "0001-99; PED-184465"
        assert pedido.facturas_documento == "KEEP-FA"
        assert pedido.numero_factura == "ERP-KEEP"

    def test_skip_comprobante_pago_and_otro(self) -> None:
        pedido = _pedido(facturas="A", pedidos="B")
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "comprobante_pago",
                "nro_documento": "REC-1",
                "nro_pedido": "PED-9",
            },
        )
        apply_writeback(
            pedido,  # type: ignore[arg-type]
            {
                "tipo_documento": "otro",
                "nro_documento": "X",
                "nro_pedido": "Y",
            },
        )
        assert pedido.facturas_documento == "A"
        assert pedido.pedidos_documento == "B"

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
