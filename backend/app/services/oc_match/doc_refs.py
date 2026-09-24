"""Append-only OC-match write-back of supplier document numbers onto PedidoCompra.

Worker persist calls apply_writeback after SELECT FOR UPDATE. Never writes
numero_factura. Never calls editar_pedido.
"""

from __future__ import annotations

from typing import Any, Optional

from app.models.pedido_compra import PedidoCompra

TIPOS_CONOCIDOS: frozenset[str] = frozenset(
    {
        "factura",
        "pedido",
        "proforma",
        "nota_venta",
        "comprobante_pago",
        "nota_credito",
        "nota_debito",
        "otro",
    }
)
TIPOS_ROUTEABLE: frozenset[str] = frozenset({"factura", "pedido", "proforma", "nota_venta"})
TIPOS_PEDIDO: frozenset[str] = frozenset({"pedido", "proforma", "nota_venta"})
TIPOS_NC_ND: frozenset[str] = frozenset({"nota_credito", "nota_debito"})

_TIPO_ALIASES: dict[str, str] = {
    "nv": "nota_venta",
    "nota de venta": "nota_venta",
    "nota_de_venta": "nota_venta",
    "comprobante": "comprobante_pago",
    "constancia": "comprobante_pago",
    "recibo": "comprobante_pago",
    "transferencia": "comprobante_pago",
    "nc": "nota_credito",
    "nota de credito": "nota_credito",
    "nota_de_credito": "nota_credito",
    "nd": "nota_debito",
    "nota de debito": "nota_debito",
    "nota_de_debito": "nota_debito",
}


def normalize_tipo(raw: object) -> str:
    """Lowercase/strip tipo_documento; map locked aliases; unknown/null → otro."""
    if raw is None:
        return "otro"
    text = str(raw).strip().lower()
    if not text:
        return "otro"
    if text in TIPOS_CONOCIDOS:
        return text
    return _TIPO_ALIASES.get(text, "otro")


def token_or_none(raw: object) -> Optional[str]:
    """Single extract token: strip only. Do not split on ';'."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def parse_tokens(stored: Optional[str]) -> list[str]:
    """Split stored column on ';' then strip. Empty parts dropped."""
    if not stored:
        return []
    return [part.strip() for part in stored.split(";") if part.strip()]


def append_unique(stored: Optional[str], token: Optional[str]) -> Optional[str]:
    """Append token if casefold-unique. Keep first-seen casing. Join with '; '."""
    incoming = token_or_none(token)
    if incoming is None:
        return stored
    existing = parse_tokens(stored)
    seen = {item.casefold() for item in existing}
    if incoming.casefold() in seen:
        return stored
    existing.append(incoming)
    return "; ".join(existing)


def apply_writeback(pedido: PedidoCompra, extracted: dict[str, Any]) -> bool:
    """Mutate only facturas_documento / pedidos_documento from a routeable extract.

    Returns True iff tipo is routeable and at least one token is present,
    even when append_unique is a no-op. False for comprobante_pago/otro/
    unknown or empty numbers. Never touches numero_factura.
    """
    tipo = normalize_tipo(extracted.get("tipo_documento"))
    if tipo not in TIPOS_ROUTEABLE:
        return False
    nro_documento = token_or_none(extracted.get("nro_documento"))
    nro_pedido = token_or_none(extracted.get("nro_pedido"))
    if nro_documento is None and nro_pedido is None:
        return False
    if tipo == "factura":
        if nro_documento is not None:
            pedido.facturas_documento = append_unique(pedido.facturas_documento, nro_documento)
        if nro_pedido is not None:
            pedido.pedidos_documento = append_unique(pedido.pedidos_documento, nro_pedido)
        return True
    if tipo in TIPOS_PEDIDO:
        if nro_documento is not None:
            pedido.pedidos_documento = append_unique(pedido.pedidos_documento, nro_documento)
        if nro_pedido is not None:
            pedido.pedidos_documento = append_unique(pedido.pedidos_documento, nro_pedido)
        return True
    return False
