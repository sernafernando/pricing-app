"""Extract proforma/factura JSON from PDF or image bytes via Gemini."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from google.genai import types

from app.services.oc_match.gemini_pool import GeminiPool

MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Unquoted leading-zero integers in these keys would lose zeros in json.loads.
_NRO_UNQUOTED_RE = re.compile(r'("(?:nro_pedido|nro_documento)"\s*:\s*)(-?\d+)(?=\s*[,}\n])')


def quote_numeric_doc_fields(text: str) -> str:
    """Quote unquoted nro_pedido/nro_documento integers so leading zeros survive json.loads."""
    return _NRO_UNQUOTED_RE.sub(r'\1"\2"', text)


def stringify_nro_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """Keep nro_pedido/nro_documento as strings. Never coerce with int()."""
    for key in ("nro_pedido", "nro_documento"):
        raw = parsed.get(key)
        if raw is None:
            parsed[key] = None
        else:
            text = str(raw).strip()
            parsed[key] = text or None
    return parsed


PROMPT = """Sos un extractor de documentos comerciales argentinos (proforma, factura, pedido, nota de venta, NC, ND).
Devolvé SOLO JSON válido con esta forma:

{
  "proveedor_razon_social": string o null,
  "proveedor_cuit": string o null,
  "cliente": string o null,
  "fecha": string o null,
  "nro_documento": string o null,
  "nro_pedido": string o null,
  "tipo_documento": "factura" | "pedido" | "proforma" | "nota_venta" | "comprobante_pago" | "nota_credito" | "nota_debito" | "otro",
  "moneda": "USD" | "ARS" | null,
  "tipo_cambio": number o null,
  "descuento_pct": number o null,
  "renglones": [
    {
      "descripcion": string,
      "cantidad": number o null,
      "precio_unitario": number o null,
      "moneda": "USD" | "ARS" | null,
      "codigo_proveedor": string o null,
      "codigo_fabricante": string o null,
      "ean": string o null,
      "ean_ultimos4": string o null,
      "omitir": boolean,
      "motivo_omitir": string o null
    }
  ]
}

Reglas:
- Extraé mercadería (ítem + cantidad + precio si está). Conservá pack (1/2/3 pack) y color/variante en descripcion.
- omitir=true para flete, marketing (ACC-COM), descuentos de pie, percepciones, IVA de totales, legales, páginas de condiciones. También para facturación rara que no se compra como SKU suelto: códigos ESFABRIC_*, “PC ELIT …” armada, y componentes explosionados de ese kit (van a mano; no a la OC automática).
- NO inventes EAN. ean solo si está escrito (p. ej. Distecna EAN/UPC). ean_ultimos4 solo si el papel trae 4 dígitos tipo (9862).
- codigo_fabricante: Part ID, alias tipo TL-SG108, M11-SF-FRGB, SDCZ410-032G-G4.
- codigo_proveedor: código interno del emisor (ARTICULO de Corcisa, código ELIT, etc.).
- proveedor_cuit: CUIT del EMISOR (quien factura), no el de Grupo Gauss. Si no está escrito en el documento, null: no lo adivines.
- No fusiones filas: si el mismo artículo aparece dos veces (distinto despacho), dos renglones.
- Tampoco fusiones SKUs distintos (p. ej. una PC armada y un procesador suelto van en renglones separados).
- cantidad y precio_unitario en números (punto decimal en JSON).
- tipo_cambio: pesos argentinos por 1 USD (o por 1 unidad de la moneda extranjera) SOLO si está escrito (Tipo de cambio, Cotización, U$S =, 1 USD = …). Número JSON con punto decimal. No inventes ni uses internet. Si el papel está en USD y no hay TC, null.
- nro_documento: factura, proforma, nota de venta (NV-…, 00099-…, 0004-00235724). STRING: conservá ceros a la izquierda. No lo inventes.
- nro_pedido: número de pedido del proveedor si está escrito (Pedido, N° pedido, DATOS DE PEDIDO, Cod. Pedido, PED-…). Ej.: Solution Box `1379491/01`, Distecna `PED-184465-…`, `00184465`. STRING: conservá ceros a la izquierda. Distinto de nro_documento. Si el papel es solo un pedido y no hay factura, nro_pedido es ese número. Playwright lo va a cargar en un campo de la OC GBP. Si no está, null.
- tipo_documento: clasificá el papel. factura = factura/invoice. pedido = orden/pedido del proveedor. proforma = proforma. nota_venta = NV / nota de venta. comprobante_pago = recibo, constancia, transferencia, comprobante de pago. nota_credito = NC / nota de crédito (NO es factura). nota_debito = ND / nota de débito (NO es factura). otro = no encaja. Un valor del enum, no lo inventes fuera de esa lista.
- descuento_pct: descuento financiero en porcentaje si está escrito (p. ej. Distecna “3% off”, “Mas descuento financiero 3%”). 3 significa 3 %. Si no hay, null. No inventes.
"""


def mime_for_filename(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    mime = MIME.get(suffix)
    if not mime:
        raise ValueError(f"Extensión no soportada: {filename}")
    return mime


def extract_one(pool: GeminiPool, data: bytes, filename: str) -> dict[str, Any]:
    """Extract JSON from adjunto bytes. No filesystem Path required."""
    parsed = pool.generate_json(
        [
            types.Part.from_bytes(data=data, mime_type=mime_for_filename(filename)),
            PROMPT,
        ],
        transform_text=quote_numeric_doc_fields,
    )
    return stringify_nro_fields(parsed)
