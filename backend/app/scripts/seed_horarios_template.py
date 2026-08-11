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
  │ DNI: ...   CUIL: ...            Período: ... │
  │ Área: ...            Puesto: ...             │
  │ ┌──────────────────────────────────────────┐ │
  │ │ Día         Entrada   Salida         Hs  │ │
  │ │  ...un renglón por día del período       │ │
  │ └──────────────────────────────────────────┘ │
  │ Total horas: HH:MM        Total días: NN     │
  │  ______________       ______________         │
  │  Firma del empleado   Por la empresa         │
  │ Emitido el: dd/mm/aaaa                       │
  └──────────────────────────────────────────────┘

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.seed_horarios_template            # seed en la DB
  python -m app.scripts.seed_horarios_template --dump-fixture  # regenera el fixture del frontend

⚠ NO modifica ningún otro template. Solo crea/actualiza el de horarios.
"""

import json
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


# ── Geometría de la tabla de días ────────────────────────────────────────────
#
# UNA sola tabla a ancho completo. NO dos lado a lado: pdfme modela la página
# como un ÚNICO FLUJO VERTICAL. En `dynamicTemplate.processDynamicPage` recorre
# las tablas en secuencia acumulando un `totalYOffset`, y ubica cada una en
# `baseY + totalYOffset`. Con dos tablas en el mismo `y`, la segunda recibe el
# desplazamiento de la primera: si la primera encoge respecto de su alto
# declarado, la segunda sube y se monta sobre el encabezado. Verificado
# renderizando con @pdfme/generator 5.5.10.
#
# Corolario: el alto de una tabla es DECLARADO PERO NO RESPETADO. pdfme lo
# recalcula segun el contenido y desplaza todo lo que va debajo. Por eso el pie
# de este template va INMEDIATAMENTE despues de la tabla y no clavado al fondo
# de la hoja: cualquier cosa fija cerca del margen inferior se cae a una
# segunda pagina apenas la tabla crece.
TABLE_W = CONTENT_W  # 180mm
# Alto declarado para ~31 filas. Con `fontSize` 8 y padding vertical de 1.0mm
# cada fila mide ~4.8mm, asi que un mes entero entra en UNA pagina.
TABLE_ROWS = 31
TABLE_H = 150.0
# Padding vertical del cuerpo. Es la palanca que decide cuantos dias entran en
# una pagina. Medido renderizando PDFs reales contra ESTE encabezado compacto:
# a 1.5mm el ultimo rango de una pagina es de 31 dias; a 1.0mm es de 37. Se usa
# 1.0 para no dejar un mes de 31 dias justo en el borde: con 6 dias de aire, un
# retoque chico del encabezado o del pie no manda el documento a dos paginas.
# (Si se toca este valor, `horariosTemplateRender.test.js` lo verifica.)
TABLE_PAD_Y = 1.0

TABLE_HEAD = ["Día", "Entrada", "Salida", "Hs"]
TABLE_HEAD_WIDTHS = [34, 23, 23, 20]  # suma 100


def _tabla_dias(name: str, x: float, y: float) -> dict:
    """
    La tabla de días del período.

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
            "padding": {"top": TABLE_PAD_Y, "bottom": TABLE_PAD_Y, "left": 3, "right": 3},
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

    ⚠ EL PIE FLUYE CON LA TABLA. pdfme recalcula el alto de una tabla segun su
    contenido y desplaza todo lo que va debajo (ver el comentario de
    `TABLE_H`). Por eso los totales, la leyenda, las firmas y la fecha de
    emision van INMEDIATAMENTE despues de la tabla, con separaciones chicas, y
    NO clavados al fondo de la hoja: cualquier elemento fijo cerca del margen
    inferior se cae a una segunda pagina apenas la tabla crece unos milimetros.

    El encabezado es deliberadamente compacto (~32mm): cada milimetro que se
    le saca es una fila mas de la tabla que entra en la primera pagina.
    """
    fields = []

    # ── Encabezado: logo + titulo + linea corporativa ────────────────────
    # El titulo va centrado sobre el ancho de contenido; a fontSize 15 ocupa el
    # tercio central, asi que no pisa el logo de la izquierda.
    y = MARGIN
    fields.append(_image("__logo__", MARGIN, y, 34, 13))
    fields.append(
        _label(
            "__titulo__",
            MARGIN,
            y + 2,
            CONTENT_W,
            9,
            "REGISTRO DE HORARIOS",
            fontSize=15,
            bold=True,
            alignment="center",
        )
    )
    y += 14
    fields.append(_line("__linea_header__", MARGIN, y, CONTENT_W))
    y += 3.5

    # ── Identidad del empleado ───────────────────────────────────────────
    fields.append(_text("nombre_completo", MARGIN, y, 118, 6.5, content="Apellido, Nombre", bold=True, fontSize=11))
    fields.append(_label("__lbl_legajo__", MARGIN + 120, y, 18, 6, "Legajo:", fontSize=8, fontColor="#555555"))
    fields.append(_text("legajo", MARGIN + 138, y, 42, 6, content="0000", bold=True, fontSize=10, alignment="right"))
    y += 7

    fields.append(_label("__lbl_dni__", MARGIN, y, 11, 5, "DNI:", fontSize=8, fontColor="#555555"))
    fields.append(_text("dni", MARGIN + 11, y, 32, 5, content="", fontSize=9))
    fields.append(_label("__lbl_cuil__", MARGIN + 45, y, 13, 5, "CUIL:", fontSize=8, fontColor="#555555"))
    fields.append(_text("cuil", MARGIN + 58, y, 38, 5, content="", fontSize=9))
    fields.append(_label("__lbl_periodo__", MARGIN + 100, y, 19, 5, "Período:", fontSize=8, fontColor="#555555"))
    fields.append(
        _text(
            "periodo",
            MARGIN + 119,
            y,
            61,
            5,
            content="dd/mm/aaaa - dd/mm/aaaa",
            bold=True,
            fontSize=9,
            alignment="right",
        )
    )
    y += 6

    fields.append(_label("__lbl_area__", MARGIN, y, 13, 5, "Área:", fontSize=8, fontColor="#555555"))
    fields.append(_text("area", MARGIN + 13, y, 55, 5, content="", fontSize=9))
    fields.append(_label("__lbl_puesto__", MARGIN + 72, y, 17, 5, "Puesto:", fontSize=8, fontColor="#555555"))
    fields.append(_text("puesto", MARGIN + 89, y, 91, 5, content="", fontSize=9))
    y += 8

    # ── Tabla de dias (UNA sola, ancho completo) ─────────────────────────
    table_y = y
    fields.append(_tabla_dias("tabla_dias", MARGIN, table_y))

    # ── Pie: va pegado a la tabla y fluye con ella ───────────────────────
    y = table_y + TABLE_H + 5
    fields.append(_label("__lbl_total_horas__", MARGIN, y, 28, 7, "Total horas:", fontSize=10))
    fields.append(_text("total_horas", MARGIN + 28, y, 35, 7, content="0:00", bold=True, fontSize=12))
    fields.append(_label("__lbl_total_dias__", MARGIN + 110, y, 28, 7, "Total días:", fontSize=10))
    fields.append(_text("total_dias", MARGIN + 138, y, 42, 7, content="0", bold=True, fontSize=12, alignment="right"))
    y += 10

    fields.append(
        _label(
            "__leyenda__",
            MARGIN,
            y,
            CONTENT_W,
            8,
            "Entrada: primera marcación del día. Salida: última marcación del día. "
            "Los días sin marcaciones informan el estado registrado.",
            fontSize=7,
            fontColor="#777777",
        )
    )
    y += 14

    fields.extend(_firmas(y, ["Firma del empleado", "Por la empresa"]))
    y += 12

    fields.append(_label("__lbl_emision__", MARGIN, y, 24, 5, "Emitido el:", fontSize=7, fontColor="#777777"))
    fields.append(_text("fecha_emision", MARGIN + 24, y, 60, 5, content="", fontSize=7, fontColor="#777777"))

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
        "para entregar junto con el recibo de sueldo. Una tabla de días a "
        "ancho completo (un mes entero en una página), totales y firmas."
    ),
    "contexto": "horarios_empleado",
    "template_json": template_horarios,
}


# =============================================================================
# FIXTURE COMPARTIDO CON EL FRONTEND
# =============================================================================
#
# El test de render del frontend (`horariosTemplateRender.test.js`) genera un
# PDF REAL contra este mismo template. Para eso necesita el schema en un
# archivo que pueda leer sin levantar Python, así que se commitea serializado.
#
# La serialización vive acá y no en el test para que el comando que regenera el
# fixture y el comando que lo verifica no puedan divergir.
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "frontend/src/test/fixtures/horarios-template.json"

# Comando exacto que regenera el fixture. Se cita en el mensaje de falla del
# test que lo verifica, así el desarrollador no tiene que ir a buscarlo.
FIXTURE_REGEN_CMD = "cd backend && python -m app.scripts.seed_horarios_template --dump-fixture"


def serializar_fixture() -> str:
    """Serializa el template tal cual queda commiteado en el fixture del frontend.

    `sort_keys` hace el diff legible y estable: sin él, reordenar dos claves en
    el builder produce un diff gigante que no cambia nada del PDF.
    """
    return json.dumps(template_horarios(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def dump_fixture() -> Path:
    """Reescribe el fixture del frontend con el template actual."""
    FIXTURE_PATH.write_text(serializar_fixture(), encoding="utf-8")
    return FIXTURE_PATH


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
    parser.add_argument(
        "--dump-fixture",
        action="store_true",
        help="Regenerar el fixture del frontend y salir (no toca la DB)",
    )
    args = parser.parse_args()

    if args.dump_fixture:
        destino = dump_fixture()
        print(f"Fixture regenerado: {destino}")
        raise SystemExit(0)

    print("Seeding template de registro de horarios...")
    result = seed_horarios_template(user_id=args.user_id, force_update=args.force_update)
    if result:
        print("Done! Template creado/actualizado.")
    else:
        print("Done! Sin cambios (ya existía, usar --force-update para sobreescribir).")
