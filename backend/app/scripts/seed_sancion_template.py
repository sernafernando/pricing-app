"""
Seed del template de SANCIÓN para el sistema de documentos.
Replica el layout del modelo de sanción corporativo:
  - Logo (placeholder de imagen) arriba a la izquierda
  - Fecha arriba a la derecha
  - Datos del empleado (nombre, legajo, sector)
  - Línea separadora horizontal
  - Cuerpo de texto de la sanción (itálica)
  - Bloque de notificación (Me notifico, Aclaración, DNI)
  - Nº Interno y paginación

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.seed_sancion_template

⚠ NO modifica ningún otro template. Solo crea/actualiza el de sanciones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import SessionLocal
from app.models.document_template import DocumentTemplate

# Dimensiones A4 en mm
A4_W = 210
A4_H = 297
MARGIN = 15
CONTENT_W = A4_W - MARGIN * 2  # 180mm

# Color de la línea separadora (azul corporativo del modelo)
LINE_COLOR = "#1a6fa0"


def _text(name: str, x: float, y: float, w: float, h: float, **kwargs) -> dict:
    """Helper para crear un campo de texto.

    Fonts disponibles en el sistema: Arial, Arial Bold.
    NO existen variantes Italic — pdfme necesita TTF por variante
    y no tenemos Arial-Italic.ttf cargado.
    """
    field = {
        "name": name,
        "type": "text",
        "content": kwargs.get("content", ""),
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
    # italic/boldItalic: no TTF disponible, usar regular/bold como fallback
    if kwargs.get("backgroundColor"):
        field["backgroundColor"] = kwargs["backgroundColor"]
    if kwargs.get("readOnly"):
        field["readOnly"] = True
    if kwargs.get("lineHeight"):
        field["lineHeight"] = kwargs["lineHeight"]
    return field


def _label(name: str, x: float, y: float, w: float, h: float, text: str, **kwargs) -> dict:
    """Helper para un label estático (readOnly, con content fijo)."""
    return _text(name, x, y, w, h, content=text, readOnly=True, **kwargs)


def _line(name: str, x: float, y: float, w: float, color: str = LINE_COLOR, height: float = 0.8) -> dict:
    """Helper para línea horizontal."""
    return {
        "name": name,
        "type": "line",
        "position": {"x": x, "y": y},
        "width": w,
        "height": height,
        "color": color,
        "readOnly": True,
        "content": "",
    }


def _image(name: str, x: float, y: float, w: float, h: float) -> dict:
    """Placeholder de imagen (logo). El usuario lo carga desde el Designer."""
    return {
        "name": name,
        "type": "image",
        "position": {"x": x, "y": y},
        "width": w,
        "height": h,
        "content": "",
    }


def _firma_linea(name: str, x: float, y: float, w: float) -> dict:
    """Línea de firma (línea fina negra/gris)."""
    return _line(name, x, y, w, color="#333333", height=0.3)


# =============================================================================
# TEMPLATE: SANCIÓN
# =============================================================================
def template_sancion() -> dict:
    """
    Layout replicando el modelo de sanción corporativo.

    Estructura:
    ┌─────────────────────────────────────────────┐
    │ [LOGO]                    Buenos Aires, ...  │
    │ Señor/a:                                     │
    │ NOMBRE EMPLEADO (bold)                       │
    │ Legajo:  XXXX                                │
    │ Sector:  XXXXXXXXXX                          │
    │ ────────────────────────────── (línea azul)  │
    │                                              │
    │ <texto de la sanción en itálica>             │
    │                                              │
    │                                              │
    │                                              │
    │                  Me notifico: ______________ │
    │                  Aclaración:  ______________ │
    │                  DNI:         ______________ │
    │ Nº Interno: XXXX                             │
    │ Página: 1 / 1                                │
    └─────────────────────────────────────────────┘
    """
    fields = []
    y = MARGIN

    # ── Logo (placeholder imagen, arriba izquierda) ──────────────────────
    fields.append(_image("__logo__", MARGIN, y, 50, 20))

    # ── Fecha (arriba derecha, itálica) ──────────────────────────────────
    fields.append(
        _text(
            "fecha_sancion",
            MARGIN + 90,
            y + 5,
            90,
            8,
            italic=True,
            fontSize=10,
            alignment="right",
        )
    )

    y += 24

    # ── Señor/a: (label estático) ────────────────────────────────────────
    fields.append(
        _label(
            "__lbl_senor__",
            MARGIN,
            y,
            40,
            6,
            "Señor/a:",
            italic=True,
            fontSize=10,
        )
    )
    y += 7

    # ── Nombre del empleado (bold, grande) ───────────────────────────────
    fields.append(
        _text(
            "empleado_nombre",
            MARGIN,
            y,
            CONTENT_W,
            9,
            bold=True,
            fontSize=13,
        )
    )
    y += 10

    # ── Legajo ───────────────────────────────────────────────────────────
    fields.append(
        _label(
            "__lbl_legajo__",
            MARGIN,
            y,
            22,
            6,
            "Legajo:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _text(
            "empleado_legajo",
            MARGIN + 23,
            y,
            40,
            6,
            bold=True,
            fontSize=10,
        )
    )
    y += 7

    # ── Sector ───────────────────────────────────────────────────────────
    fields.append(
        _label(
            "__lbl_sector__",
            MARGIN,
            y,
            22,
            6,
            "Sector:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _text(
            "empleado_sector",
            MARGIN + 23,
            y,
            120,
            6,
            italic=True,
            fontSize=10,
        )
    )
    y += 9

    # ── Línea separadora horizontal (azul corporativo) ───────────────────
    fields.append(_line("__linea_header__", MARGIN, y, CONTENT_W))
    y += 5

    # ── Cuerpo del texto de la sanción (itálica, multilínea) ─────────────
    # Altura generosa para texto largo. El texto viene del campo texto_sancion
    # que el usuario configura con placeholders de fechas, etc.
    fields.append(
        _text(
            "texto_sancion",
            MARGIN + 15,
            y,
            CONTENT_W - 15,
            120,
            italic=True,
            fontSize=10,
            lineHeight=1.5,
            alignment="left",
        )
    )

    # ── Bloque de notificación (firma del empleado) ──────────────────────
    # Posición fija cerca del pie de página
    firma_x = MARGIN + 85  # Alineado a la derecha
    firma_w = 80
    firma_label_w = 38
    y_firma = A4_H - MARGIN - 72

    # Me notifico:
    fields.append(
        _label(
            "__lbl_notifico__",
            firma_x,
            y_firma,
            firma_label_w,
            6,
            "Me notifico:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _firma_linea(
            "__firma_notifico__",
            firma_x + firma_label_w + 2,
            y_firma + 5,
            firma_w,
        )
    )
    y_firma += 14

    # Aclaración:
    fields.append(
        _label(
            "__lbl_aclaracion__",
            firma_x,
            y_firma,
            firma_label_w,
            6,
            "Aclaración:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _firma_linea(
            "__firma_aclaracion__",
            firma_x + firma_label_w + 2,
            y_firma + 5,
            firma_w,
        )
    )
    y_firma += 14

    # DNI:
    fields.append(
        _label(
            "__lbl_dni__",
            firma_x,
            y_firma,
            firma_label_w,
            6,
            "DNI:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _firma_linea(
            "__firma_dni__",
            firma_x + firma_label_w + 2,
            y_firma + 5,
            firma_w,
        )
    )

    # ── Nº Interno (pie izquierdo) ──────────────────────────────────────
    y_pie = A4_H - MARGIN - 18
    fields.append(
        _label(
            "__lbl_interno__",
            MARGIN,
            y_pie,
            28,
            6,
            "Nº Interno:",
            italic=True,
            fontSize=10,
        )
    )
    fields.append(
        _text(
            "numero_interno",
            MARGIN + 30,
            y_pie,
            40,
            6,
            fontSize=10,
        )
    )

    # ── Paginación (pie izquierdo, debajo de Nº Interno) ────────────────
    fields.append(
        _label(
            "__paginacion__",
            MARGIN,
            y_pie + 8,
            60,
            5,
            "Página :   1   /  1",
            fontSize=8,
            fontColor="#666666",
        )
    )

    return {
        "basePdf": {
            "width": A4_W,
            "height": A4_H,
            "padding": [MARGIN, MARGIN, MARGIN, MARGIN],
        },
        "schemas": [fields],
    }


# =============================================================================
# SEED (solo sanciones)
# =============================================================================

TEMPLATE_SANCION = {
    "nombre": "Sanción Disciplinaria (base)",
    "descripcion": (
        "Template base para sanciones disciplinarias. "
        "Incluye logo, datos del empleado, cuerpo de la sanción, "
        "bloque de notificación (firma), Nº interno y paginación."
    ),
    "contexto": "sanciones",
    "template_json": template_sancion,
}


def seed_sancion_template(user_id: int = 1, force_update: bool = False) -> int:
    """
    Inserta o actualiza SOLO el template de sanciones.
    No toca ningún otro template.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(DocumentTemplate)
            .filter(
                DocumentTemplate.nombre == TEMPLATE_SANCION["nombre"],
                DocumentTemplate.contexto == TEMPLATE_SANCION["contexto"],
            )
            .first()
        )

        if existing:
            if force_update:
                existing.template_json = TEMPLATE_SANCION["template_json"]()
                db.commit()
                print(f"  🔄 Actualizado: {TEMPLATE_SANCION['nombre']} ({TEMPLATE_SANCION['contexto']})")
                return 1
            else:
                print(f"  ⏭ Ya existe: {TEMPLATE_SANCION['nombre']} ({TEMPLATE_SANCION['contexto']})")
                return 0

        template = DocumentTemplate(
            nombre=TEMPLATE_SANCION["nombre"],
            descripcion=TEMPLATE_SANCION["descripcion"],
            contexto=TEMPLATE_SANCION["contexto"],
            template_json=TEMPLATE_SANCION["template_json"](),
            creado_por_id=user_id,
        )
        db.add(template)
        db.commit()
        print(f"  ✓ Creado: {TEMPLATE_SANCION['nombre']} ({TEMPLATE_SANCION['contexto']})")
        return 1

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed template de sanción disciplinaria")
    parser.add_argument("--user-id", type=int, default=1, help="ID del usuario creador (default: 1)")
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Actualizar template existente con la versión del seed",
    )
    args = parser.parse_args()

    print("Seeding template de sanción...")
    result = seed_sancion_template(user_id=args.user_id, force_update=args.force_update)
    if result:
        print("Done! Template creado/actualizado.")
    else:
        print("Done! Sin cambios (ya existía, usar --force-update para sobreescribir).")
