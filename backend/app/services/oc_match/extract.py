"""Extract proforma/factura JSON from PDF or image bytes via Gemini."""

from __future__ import annotations

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

PROMPT = """Sos un extractor de documentos comerciales argentinos (proforma, factura, pedido, nota de venta).
Devolvé SOLO JSON válido con esta forma:

{
  "proveedor_razon_social": string o null,
  "proveedor_cuit": string o null,
  "cliente": string o null,
  "fecha": string o null,
  "nro_documento": string o null,
  "nro_pedido": string o null,
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
- nro_documento: factura, proforma, nota de venta (NV-…, 00099-…, 0004-00235724). No lo inventes.
- nro_pedido: número de pedido del proveedor si está escrito (Pedido, N° pedido, DATOS DE PEDIDO, Cod. Pedido, PED-…). Ej.: Solution Box `1379491/01`, Distecna `PED-184465-…`. Distinto de nro_documento. Si el papel es solo un pedido y no hay factura, nro_pedido es ese número. Playwright lo va a cargar en un campo de la OC GBP. Si no está, null.
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
    return pool.generate_json(
        [
            types.Part.from_bytes(data=data, mime_type=mime_for_filename(filename)),
            PROMPT,
        ]
    )
