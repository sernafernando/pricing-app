"""
Seed de templates base para el sistema de documentos.
Crea un remito base para cada contexto con los campos más comunes.

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.seed_document_templates

Requiere que la migración 20260317_doc_templates ya esté aplicada.
"""

import sys
from pathlib import Path

# Agregar backend al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import SessionLocal
from app.models.document_template import DocumentTemplate

# Dimensiones A4 en mm
A4_W = 210
A4_H = 297
MARGIN = 15
CONTENT_W = A4_W - MARGIN * 2  # 180mm


def _text(name, x, y, w, h, **kwargs):
    """Helper para crear un campo de texto."""
    field = {
        "name": name,
        "type": "text",
        "position": {"x": x, "y": y},
        "width": w,
        "height": h,
        "fontSize": kwargs.get("fontSize", 10),
        "fontName": kwargs.get("fontName", "Arial"),
        "alignment": kwargs.get("alignment", "left"),
        "fontColor": kwargs.get("fontColor", "#000000"),
    }
    if kwargs.get("bold"):
        field["fontName"] = "Arial Bold"
    if kwargs.get("backgroundColor"):
        field["backgroundColor"] = kwargs["backgroundColor"]
    return field


def _header_block(title, y_start=MARGIN):
    """Bloque de encabezado reutilizable: título + fecha."""
    y = y_start
    fields = [
        # Título del documento
        _text(
            "__titulo__",
            MARGIN,
            y,
            CONTENT_W,
            12,
            fontSize=18,
            bold=True,
            alignment="center",
        ),
    ]
    y += 14
    fields.append(
        # Línea separadora (campo vacío con fondo)
        {
            "name": "__linea_header__",
            "type": "text",
            "position": {"x": MARGIN, "y": y},
            "width": CONTENT_W,
            "height": 0.5,
            "fontSize": 1,
            "fontColor": "#ffffff",
            "backgroundColor": "#333333",
        }
    )
    return fields, y + 3


def _firma_block(y_start, labels=None):
    """Bloque de firmas al pie."""
    if labels is None:
        labels = ["Firma", "Aclaración"]
    fields = []
    col_w = CONTENT_W / len(labels)
    for i, label in enumerate(labels):
        x = MARGIN + i * col_w
        # Línea de firma
        fields.append(
            {
                "name": f"__firma_linea_{i}__",
                "type": "text",
                "position": {"x": x + 10, "y": y_start},
                "width": col_w - 20,
                "height": 0.3,
                "fontSize": 1,
                "fontColor": "#ffffff",
                "backgroundColor": "#666666",
            }
        )
        # Label bajo la línea
        fields.append(
            _text(
                f"__firma_label_{i}__",
                x + 10,
                y_start + 1,
                col_w - 20,
                6,
                fontSize=8,
                alignment="center",
                fontColor="#666666",
            )
        )
    return fields


# =============================================================================
# TEMPLATE: PEDIDOS
# =============================================================================
def template_pedidos():
    fields = []
    # Header
    header, y = _header_block("REMITO DE PEDIDO")
    fields.extend(header)

    # Nro pedido + fecha
    y += 2
    fields.append(_text("pedido_id", MARGIN, y, 60, 8, bold=True, fontSize=12))
    fields.append(_text("fecha_pedido", MARGIN + 120, y, 60, 8, alignment="right"))
    y += 12

    # Sección cliente
    fields.append(_text("__sec_cliente__", MARGIN, y, 60, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("cliente_nombre", MARGIN, y, CONTENT_W, 7, bold=True, fontSize=11))
    y += 8
    fields.append(_text("cliente_cuit", MARGIN, y, 90, 6))
    fields.append(_text("cliente_telefono", MARGIN + 90, y, 90, 6))
    y += 7
    fields.append(_text("cliente_direccion", MARGIN, y, CONTENT_W, 6))
    y += 7
    fields.append(_text("cliente_ciudad", MARGIN, y, 60, 6))
    fields.append(_text("cliente_cp", MARGIN + 60, y, 30, 6))
    fields.append(_text("cliente_email", MARGIN + 100, y, 80, 6))
    y += 10

    # Sección envío
    fields.append(_text("__sec_envio__", MARGIN, y, 60, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("destinatario", MARGIN, y, 90, 7, bold=True))
    fields.append(_text("bultos", MARGIN + 130, y, 50, 7, alignment="right", bold=True, fontSize=12))
    y += 8
    fields.append(_text("direccion_envio", MARGIN, y, CONTENT_W, 6))
    y += 8
    fields.append(_text("ml_id", MARGIN, y, 90, 6, fontSize=9))
    fields.append(_text("ml_guia", MARGIN + 90, y, 90, 6, fontSize=9))
    y += 10

    # Observaciones
    fields.append(_text("__sec_obs__", MARGIN, y, 60, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("observacion", MARGIN, y, CONTENT_W, 20))
    y += 24

    # Total
    fields.append(_text("total", MARGIN + 100, y, 80, 10, bold=True, fontSize=14, alignment="right"))
    y += 14
    fields.append(_text("fecha_entrega", MARGIN, y, 90, 6, fontSize=9, fontColor="#555555"))

    # Firmas
    y = A4_H - MARGIN - 15
    fields.extend(_firma_block(y, ["Entregó", "Recibió"]))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# TEMPLATE: RRHH (Legajo)
# =============================================================================
def template_rrhh():
    fields = []
    header, y = _header_block("FICHA DE EMPLEADO")
    fields.extend(header)

    y += 2
    # Legajo + estado
    fields.append(_text("legajo", MARGIN, y, 60, 8, bold=True, fontSize=12))
    fields.append(_text("estado", MARGIN + 130, y, 50, 8, alignment="right", bold=True))
    y += 12

    # Datos personales
    fields.append(_text("__sec_personal__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("nombre_completo", MARGIN, y, CONTENT_W, 8, bold=True, fontSize=13))
    y += 10
    fields.append(_text("dni", MARGIN, y, 60, 6))
    fields.append(_text("cuil", MARGIN + 60, y, 60, 6))
    fields.append(_text("fecha_nacimiento", MARGIN + 120, y, 60, 6))
    y += 8
    fields.append(_text("domicilio", MARGIN, y, CONTENT_W, 6))
    y += 8
    fields.append(_text("telefono", MARGIN, y, 90, 6))
    fields.append(_text("email_personal", MARGIN + 90, y, 90, 6))
    y += 10

    # Contacto emergencia
    fields.append(_text("__sec_emergencia__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("contacto_emergencia", MARGIN, y, 90, 6))
    fields.append(_text("contacto_emergencia_tel", MARGIN + 90, y, 90, 6))
    y += 10

    # Datos laborales
    fields.append(_text("__sec_laboral__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("puesto", MARGIN, y, 90, 7, bold=True))
    fields.append(_text("area", MARGIN + 90, y, 90, 7, bold=True))
    y += 8
    fields.append(_text("fecha_ingreso", MARGIN, y, 60, 6))
    fields.append(_text("fecha_egreso", MARGIN + 60, y, 60, 6))
    y += 10

    # Observaciones
    fields.append(_text("__sec_obs__", MARGIN, y, 60, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("observaciones", MARGIN, y, CONTENT_W, 30))

    # Firmas
    y = A4_H - MARGIN - 15
    fields.extend(_firma_block(y, ["Empleado", "RRHH"]))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# TEMPLATE: ENVIOS (Remito flex — envíos pistoleados por logística)
# =============================================================================
def template_envios():
    fields = []
    header, y = _header_block("REMITO DE ENVÍOS FLEX")
    fields.extend(header)

    y += 2
    fields.append(_text("fecha_envio", MARGIN, y, 60, 8, bold=True, fontSize=12))
    y += 12

    # Transporte / Logística
    fields.append(_text("__sec_transporte__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("logistica", MARGIN, y, 90, 7, bold=True, fontSize=11))
    fields.append(_text("transporte", MARGIN + 90, y, 90, 7, bold=True, fontSize=11))
    y += 8
    fields.append(_text("transporte_direccion", MARGIN, y, 90, 6))
    fields.append(_text("transporte_telefono", MARGIN + 90, y, 90, 6))
    y += 10

    # Totales (bien grandes — es lo que importa)
    fields.append(_text("__sec_totales__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 10
    fields.append(_text("total_envios", MARGIN, y, 80, 16, bold=True, fontSize=28))
    fields.append(_text("total_bultos", MARGIN + 90, y, 90, 16, bold=True, fontSize=28))
    y += 22

    # Resumen por cordón
    fields.append(_text("__sec_cordones__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("resumen_cordones", MARGIN, y, CONTENT_W, 8, fontSize=11))

    # Firmas
    y = A4_H - MARGIN - 15
    fields.extend(_firma_block(y, ["Despachó", "Logística"]))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# TEMPLATE: PRODUCTOS
# =============================================================================
def template_productos():
    fields = []
    header, y = _header_block("FICHA DE PRODUCTO")
    fields.extend(header)

    y += 2
    fields.append(_text("codigo", MARGIN, y, 90, 8, bold=True, fontSize=12))
    y += 12

    # Datos del producto
    fields.append(_text("__sec_producto__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("descripcion", MARGIN, y, CONTENT_W, 8, bold=True, fontSize=12))
    y += 10
    fields.append(_text("marca", MARGIN, y, 90, 7))
    fields.append(_text("categoria", MARGIN + 90, y, 90, 7))
    y += 10

    # Precios
    fields.append(_text("__sec_precios__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("costo", MARGIN, y, 60, 7))
    fields.append(_text("moneda_costo", MARGIN + 60, y, 30, 7))
    y += 8
    fields.append(_text("precio_lista_ml", MARGIN, y, 60, 7))
    fields.append(_text("precio_pvp", MARGIN + 60, y, 60, 7))
    fields.append(_text("precio_web_transferencia", MARGIN + 120, y, 60, 7))
    y += 10

    # Stock
    fields.append(_text("__sec_stock__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("stock", MARGIN, y, 60, 10, bold=True, fontSize=16))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# TEMPLATE: VENTAS
# =============================================================================
def template_ventas():
    fields = []
    header, y = _header_block("COMPROBANTE DE VENTA")
    fields.extend(header)

    y += 2
    fields.append(_text("id_venta", MARGIN, y, 60, 8, bold=True, fontSize=12))
    fields.append(_text("fecha", MARGIN + 120, y, 60, 8, alignment="right"))
    y += 12

    # Operación
    fields.append(_text("__sec_operacion__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("id_operacion", MARGIN, y, 90, 7, fontSize=9))
    y += 10

    # Producto
    fields.append(_text("__sec_producto__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("descripcion", MARGIN, y, CONTENT_W, 7, bold=True))
    y += 8
    fields.append(_text("codigo_item", MARGIN, y, 60, 6))
    fields.append(_text("marca", MARGIN + 60, y, 60, 6))
    fields.append(_text("categoria", MARGIN + 120, y, 60, 6))
    y += 10

    # Montos
    fields.append(_text("__sec_montos__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("cantidad", MARGIN, y, 40, 7))
    fields.append(_text("monto_unitario", MARGIN + 60, y, 60, 7, alignment="right"))
    y += 8
    fields.append(_text("monto_total", MARGIN + 60, y, 60, 10, bold=True, fontSize=14, alignment="right"))

    # Firmas
    y = A4_H - MARGIN - 15
    fields.extend(_firma_block(y, ["Vendedor", "Cliente"]))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# TEMPLATE: RMA
# =============================================================================
def template_rma():
    fields = []
    header, y = _header_block("COMPROBANTE RMA")
    fields.extend(header)

    y += 2
    fields.append(_text("numero_caso", MARGIN, y, 90, 8, bold=True, fontSize=12))
    fields.append(_text("fecha_caso", MARGIN + 120, y, 60, 8, alignment="right"))
    y += 12

    # Cliente
    fields.append(_text("__sec_cliente__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("cliente_nombre", MARGIN, y, CONTENT_W, 7, bold=True, fontSize=11))
    y += 8
    fields.append(_text("cliente_dni", MARGIN, y, 60, 6))
    fields.append(_text("ml_id", MARGIN + 60, y, 90, 6, fontSize=9))
    y += 10

    # Caso
    fields.append(_text("__sec_caso__", MARGIN, y, 80, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("origen", MARGIN, y, 60, 7))
    fields.append(_text("estado", MARGIN + 90, y, 90, 7, bold=True))
    y += 10

    # Observaciones
    fields.append(_text("__sec_obs__", MARGIN, y, 60, 7, fontSize=9, bold=True, fontColor="#555555"))
    y += 8
    fields.append(_text("observaciones", MARGIN, y, CONTENT_W, 40))

    # Firmas
    y = A4_H - MARGIN - 15
    fields.extend(_firma_block(y, ["Responsable", "Cliente"]))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# SEED
# =============================================================================

TEMPLATES = [
    {
        "nombre": "Remito de Pedido (base)",
        "descripcion": "Template base para remitos de pedido. Incluye datos de cliente, envío, y totales.",
        "contexto": "pedidos",
        "template_json": template_pedidos,
    },
    {
        "nombre": "Ficha de Empleado (base)",
        "descripcion": "Template base para ficha/legajo de empleado. Datos personales, laborales y emergencia.",
        "contexto": "rrhh",
        "template_json": template_rrhh,
    },
    {
        "nombre": "Remito Flex (base)",
        "descripcion": "Remito de envíos flex pistoleados. Logística/transporte, totales, resumen por cordón, tabla con detalle por envío (caja, bultos).",
        "contexto": "envios",
        "template_json": template_envios,
    },
    {
        "nombre": "Ficha de Producto (base)",
        "descripcion": "Template base para ficha de producto. Descripción, precios, stock.",
        "contexto": "productos",
        "template_json": template_productos,
    },
    {
        "nombre": "Comprobante de Venta (base)",
        "descripcion": "Template base para comprobante de venta. Producto, cantidades, montos.",
        "contexto": "ventas",
        "template_json": template_ventas,
    },
    {
        "nombre": "Comprobante RMA (base)",
        "descripcion": "Template base para comprobante de caso RMA. Cliente, caso, observaciones.",
        "contexto": "rma",
        "template_json": template_rma,
    },
]


def seed_templates(user_id: int = 1):
    """
    Inserta los templates base si no existen.
    Usa user_id=1 (admin) como creador por defecto.
    """
    db = SessionLocal()
    created = 0
    skipped = 0

    try:
        for tmpl in TEMPLATES:
            # Verificar si ya existe por nombre + contexto
            existing = (
                db.query(DocumentTemplate)
                .filter(
                    DocumentTemplate.nombre == tmpl["nombre"],
                    DocumentTemplate.contexto == tmpl["contexto"],
                )
                .first()
            )

            if existing:
                print(f"  ⏭ Ya existe: {tmpl['nombre']} ({tmpl['contexto']})")
                skipped += 1
                continue

            template = DocumentTemplate(
                nombre=tmpl["nombre"],
                descripcion=tmpl["descripcion"],
                contexto=tmpl["contexto"],
                template_json=tmpl["template_json"](),  # Ejecutar la función
                creado_por_id=user_id,
            )
            db.add(template)
            db.commit()
            print(f"  ✓ Creado: {tmpl['nombre']} ({tmpl['contexto']})")
            created += 1

    finally:
        db.close()

    print(f"\nResumen: {created} creados, {skipped} existentes")
    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed document templates base")
    parser.add_argument("--user-id", type=int, default=1, help="ID del usuario creador (default: 1)")
    args = parser.parse_args()

    print("Seeding document templates...")
    seed_templates(user_id=args.user_id)
    print("Done!")
