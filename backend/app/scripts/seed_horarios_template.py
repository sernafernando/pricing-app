"""
Seed del template REGISTRO DE HORARIOS (contexto `horarios_empleado`).

Documento imprimible que se entrega al empleado junto con el recibo de sueldo:
un renglón por día hábil con entrada, salida y horas. Los datos los provee
`GET /api/rrhh/reportes/horarios-documento`; el PDF lo arma el frontend con
@pdfme/generator.

Layout A4 vertical (modelado sobre `seed_sancion_template`, el template más
terminado del repo: logo, línea corporativa y líneas de firma reales):
  ┌──────────────────────────────────────────────┐
  │ [LOGO]     REGISTRO DE HORARIOS              │
  │ ──────────────────────────────────────────── │  ← línea azul corporativa
  │ NOMBRE COMPLETO                 Legajo: XXXX │
  │ DNI: ...   CUIL: ...            Área: ...    │
  │ Puesto: ...                     Período: ... │
  │ ┌────────────────┐  ┌────────────────┐       │
  │ │ Día Ent Sal Hs │  │ Día Ent Sal Hs │       │
  │ │  ...16 filas   │  │  ...16 filas   │       │
  │ └────────────────┘  └────────────────┘       │
  │ Total horas: HH:MM        Total días: NN     │
  │  ______________       ______________         │
  │  Firma del empleado   Por la empresa         │
  │ Emitido el: dd/mm/aaaa                       │
  └──────────────────────────────────────────────┘

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.seed_horarios_template

⚠ NO modifica ningún otro template. Solo crea/actualiza el de horarios.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import SessionLocal
from app.models.document_template import DocumentTemplate

# Se reutilizan las constantes de geometría y los helpers de texto del seed
# base. NO se reutilizan `_header_block` ni `_firma_block`: ambos dibujan sus
# líneas como campos `text` de 0.3-0.5mm de alto con `backgroundColor`, un
# workaround que sobrevive de antes de que el plugin `line` estuviera
# habilitado. Hoy `line` sí está en `frontend/src/utils/pdfmePlugins.js`, y el
# template de sanciones —el más terminado del repo— ya usa el tipo real. Este
# documento sigue ese modelo.
from app.scripts.seed_document_templates import (
    A4_H,
    A4_W,
    CONTENT_W,
    MARGIN,
    _label,
    _text,
)

# Azul corporativo, mismo valor que `seed_sancion_template.LINE_COLOR`.
LINE_COLOR = "#1a6fa0"


def _line(name: str, x: float, y: float, w: float, color: str = LINE_COLOR, height: float = 0.8) -> dict:
    """Línea horizontal usando el tipo `line` real de pdfme."""
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
    """Placeholder de imagen (logo). Se carga desde el Diseñador de Documentos.

    Queda con `content` vacío a propósito: mientras nadie suba el logo, el hook
    `useDocumentGenerator` no lo incluye en `templateDefaults` y pdfme
    simplemente no dibuja nada. Una vez cargado desde el Diseñador, el base64
    queda persistido en `content` y viaja con el template.
    """
    return {
        "name": name,
        "type": "image",
        "position": {"x": x, "y": y},
        "width": w,
        "height": h,
        "content": "",
    }


def _firmas(y: float, labels: list[str]) -> list[dict]:
    """Bloque de firmas al pie, con líneas reales en vez de campos con fondo.

    Conserva los nombres `__firma_linea_N__` / `__firma_label_N__` del helper
    base para no romper a quien ya lea esos campos.
    """
    fields: list[dict] = []
    col_w = CONTENT_W / len(labels)
    for i, label in enumerate(labels):
        x = MARGIN + i * col_w
        fields.append(_line(f"__firma_linea_{i}__", x + 10, y, col_w - 20, color="#333333", height=0.3))
        fields.append(
            _label(
                f"__firma_label_{i}__",
                x + 10,
                y + 1,
                col_w - 20,
                6,
                label,
                fontSize=8,
                alignment="center",
                fontColor="#666666",
            )
        )
    return fields


# ── Geometría de las dos tablas ──────────────────────────────────────────────
# 85mm + 10mm de gap + 85mm = 180mm = CONTENT_W.
TABLE_W = 85.0
TABLE_GAP = 10.0
# Alto fijo dimensionado para ~16 filas + encabezado (fontSize 8 con padding
# vertical 1.5mm ≈ 5.8mm por fila). Dos tablas de 16 ⇒ hasta ~32 días hábiles
# (≈6 semanas) en UNA sola página.
TABLE_ROWS = 16
TABLE_H = 120.0

TABLE_HEAD = ["Día", "Entrada", "Salida", "Hs"]
TABLE_HEAD_WIDTHS = [34, 23, 23, 20]  # suma 100


def _tabla_dias(name: str, x: float, y: float) -> dict:
    """
    Una de las dos columnas de días.

    La estructura de estilos se copia del `tabla_items` que ya funciona en
    producción (`seed_document_templates.template_remito_manual`): pdfme v5
    exige que `padding` y `borderWidth` sean OBJETOS `{top,right,bottom,left}`,
    no escalares, y rompe silenciosamente si falta alguna clave.

    `columnStyles` se deja vacío a propósito, igual que en el template de
    remito: es la única forma verificada contra pdfme v5 en este repo.
    """
    return {
        "name": name,
        "type": "table",
        "content": "",
        "position": {"x": x, "y": y},
        "width": TABLE_W,
        "height": TABLE_H,
        "head": list(TABLE_HEAD),
        "headWidthPercentages": list(TABLE_HEAD_WIDTHS),
        "tableStyles": {"borderWidth": 0.3, "borderColor": "#999999"},
        "headStyles": {
            "fontName": "Arial Bold",
            "fontSize": 8,
            "characterSpacing": 0,
            "alignment": "left",
            "verticalAlignment": "middle",
            "lineHeight": 1,
            "fontColor": "#ffffff",
            "backgroundColor": "#333333",
            "borderColor": "#333333",
            "padding": {"top": 3, "bottom": 3, "left": 3, "right": 3},
            "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0},
        },
        "bodyStyles": {
            "fontName": "Arial",
            "fontSize": 8,
            "characterSpacing": 0,
            "alignment": "left",
            "verticalAlignment": "middle",
            "lineHeight": 1,
            "fontColor": "#333333",
            "borderColor": "#cccccc",
            "alternateBackgroundColor": "#f5f5f5",
            "padding": {"top": 1.5, "bottom": 1.5, "left": 3, "right": 3},
            "borderWidth": {"top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
        },
        "columnStyles": {},
    }


# =============================================================================
# TEMPLATE: REGISTRO DE HORARIOS
# =============================================================================
def template_horarios() -> dict:
    """
    Arma el schema pdfme del registro de horarios.

    ⚠ GEOMETRÍA FIJA: las tablas NO reflowan. `TABLE_H` es alto declarado, no
    alto calculado, así que todo lo que va debajo (totales, firmas) usa `y`
    hardcodeado. Si se cambia `TABLE_H`, `TABLE_ROWS` o el `fontSize` del
    cuerpo, hay que recalcular a mano las posiciones del pie — y si el
    frontend manda más de `TABLE_ROWS` filas por tabla, la tabla crece hacia
    abajo y pisa el bloque de totales.
    """
    fields = []

    # ── Encabezado: logo + título + línea corporativa ────────────────────
    # El logo va arriba a la izquierda y el título centrado sobre el ancho de
    # contenido; a fontSize 18 el título ocupa el tercio central, así que no
    # pisa el logo.
    y = MARGIN
    fields.append(_image("__logo__", MARGIN, y, 45, 18))
    fields.append(
        _label(
            "__titulo__",
            MARGIN,
            y + 4,
            CONTENT_W,
            12,
            "REGISTRO DE HORARIOS",
            fontSize=18,
            bold=True,
            alignment="center",
        )
    )
    y += 20
    fields.append(_line("__linea_header__", MARGIN, y, CONTENT_W))
    y += 5

    # ── Identidad del empleado ───────────────────────────────────────────
    fields.append(_text("nombre_completo", MARGIN, y, 120, 8, content="Apellido, Nombre", bold=True, fontSize=12))
    fields.append(_label("__lbl_legajo__", MARGIN + 122, y, 20, 7, "Legajo:", fontSize=9, fontColor="#555555"))
    fields.append(_text("legajo", MARGIN + 142, y, 38, 7, content="0000", bold=True, fontSize=10))
    y += 10

    fields.append(_label("__lbl_dni__", MARGIN, y, 12, 6, "DNI:", fontSize=9, fontColor="#555555"))
    fields.append(_text("dni", MARGIN + 12, y, 40, 6, content=""))
    fields.append(_label("__lbl_cuil__", MARGIN + 55, y, 14, 6, "CUIL:", fontSize=9, fontColor="#555555"))
    fields.append(_text("cuil", MARGIN + 69, y, 45, 6, content=""))
    fields.append(_label("__lbl_area__", MARGIN + 122, y, 14, 6, "Área:", fontSize=9, fontColor="#555555"))
    fields.append(_text("area", MARGIN + 136, y, 44, 6, content=""))
    y += 8

    fields.append(_label("__lbl_puesto__", MARGIN, y, 18, 6, "Puesto:", fontSize=9, fontColor="#555555"))
    fields.append(_text("puesto", MARGIN + 18, y, 70, 6, content=""))
    fields.append(_label("__lbl_periodo__", MARGIN + 100, y, 20, 6, "Período:", fontSize=9, fontColor="#555555"))
    fields.append(
        _text(
            "periodo",
            MARGIN + 120,
            y,
            60,
            6,
            content="dd/mm/aaaa - dd/mm/aaaa",
            bold=True,
            alignment="right",
        )
    )
    y += 10

    # ── Dos tablas de días, lado a lado ──────────────────────────────────
    table_y = y
    fields.append(_tabla_dias("tabla_dias_1", MARGIN, table_y))
    fields.append(_tabla_dias("tabla_dias_2", MARGIN + TABLE_W + TABLE_GAP, table_y))

    # ── Totales (posición fija: no dependen de cuántos días haya) ────────
    y = table_y + TABLE_H + 6
    fields.append(_label("__lbl_total_horas__", MARGIN, y, 30, 7, "Total horas:", fontSize=10))
    fields.append(_text("total_horas", MARGIN + 30, y, 35, 7, content="0:00", bold=True, fontSize=12))
    fields.append(_label("__lbl_total_dias__", MARGIN + 110, y, 28, 7, "Total días:", fontSize=10))
    fields.append(_text("total_dias", MARGIN + 138, y, 42, 7, content="0", bold=True, fontSize=12, alignment="right"))
    y += 12

    fields.append(
        _label(
            "__leyenda__",
            MARGIN,
            y,
            CONTENT_W,
            10,
            "Entrada: primera marcación del día. Salida: última marcación del día. "
            "Los días sin marcaciones informan el estado registrado.",
            fontSize=7,
            fontColor="#777777",
        )
    )

    # ── Firmas: siempre al fondo de la página ────────────────────────────
    fields.extend(_firmas(A4_H - MARGIN - 15, ["Firma del empleado", "Por la empresa"]))

    # ── Pie: fecha de emisión ────────────────────────────────────────────
    # Un documento que respalda una liquidación tiene que decir cuándo se
    # emitió; sin eso no se puede distinguir una reimpresión posterior.
    # `- 6` y no `- 4`: con alto 5 el campo tiene que cerrar en el margen
    # inferior (A4_H - MARGIN), no pasarse.
    y_pie = A4_H - MARGIN - 6
    fields.append(_label("__lbl_emision__", MARGIN, y_pie, 24, 5, "Emitido el:", fontSize=7, fontColor="#777777"))
    fields.append(_text("fecha_emision", MARGIN + 24, y_pie, 60, 5, content="", fontSize=7, fontColor="#777777"))

    return {
        "basePdf": {"width": A4_W, "height": A4_H, "padding": [MARGIN, MARGIN, MARGIN, MARGIN]},
        "schemas": [fields],
    }


# =============================================================================
# SEED (solo horarios_empleado)
# =============================================================================

TEMPLATE_HORARIOS = {
    "nombre": "Registro de Horarios (base)",
    "descripcion": (
        "Registro imprimible de entradas y salidas diarias por empleado, "
        "para entregar junto con el recibo de sueldo. Dos tablas de días "
        "lado a lado (~32 días hábiles en una página), totales y firmas."
    ),
    "contexto": "horarios_empleado",
    "template_json": template_horarios,
}


def seed_horarios_template(user_id: int = 1, force_update: bool = False) -> int:
    """
    Inserta o actualiza SOLO el template de horarios.

    `user_id` es el `creado_por_id` (FK NOT NULL a `usuarios`); por defecto 1
    (admin), igual que el resto de los seeds de templates.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(DocumentTemplate)
            .filter(
                DocumentTemplate.nombre == TEMPLATE_HORARIOS["nombre"],
                DocumentTemplate.contexto == TEMPLATE_HORARIOS["contexto"],
            )
            .first()
        )

        if existing:
            if force_update:
                existing.template_json = TEMPLATE_HORARIOS["template_json"]()
                db.commit()
                print(f"  🔄 Actualizado: {TEMPLATE_HORARIOS['nombre']} ({TEMPLATE_HORARIOS['contexto']})")
                return 1
            print(f"  ⏭ Ya existe: {TEMPLATE_HORARIOS['nombre']} ({TEMPLATE_HORARIOS['contexto']})")
            return 0

        template = DocumentTemplate(
            nombre=TEMPLATE_HORARIOS["nombre"],
            descripcion=TEMPLATE_HORARIOS["descripcion"],
            contexto=TEMPLATE_HORARIOS["contexto"],
            template_json=TEMPLATE_HORARIOS["template_json"](),
            creado_por_id=user_id,
        )
        db.add(template)
        db.commit()
        print(f"  ✓ Creado: {TEMPLATE_HORARIOS['nombre']} ({TEMPLATE_HORARIOS['contexto']})")
        return 1

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed template de registro de horarios")
    parser.add_argument("--user-id", type=int, default=1, help="ID del usuario creador (default: 1)")
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Actualizar template existente con la versión del seed",
    )
    args = parser.parse_args()

    print("Seeding template de registro de horarios...")
    result = seed_horarios_template(user_id=args.user_id, force_update=args.force_update)
    if result:
        print("Done! Template creado/actualizado.")
    else:
        print("Done! Sin cambios (ya existía, usar --force-update para sobreescribir).")
