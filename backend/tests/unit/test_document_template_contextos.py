"""Paridad entre `CONTEXTOS_VALIDOS` y el registro de variables.

`GET /api/document-templates/variables/{contexto}` devuelve 404 cuando el
contexto no está en `VARIABLES_POR_CONTEXTO`. Un contexto declarado válido en
el modelo pero sin variables registradas pasa la validación del schema y
después rompe el Designer, así que la paridad se testea explícitamente.
"""

from __future__ import annotations

from app.models.document_template import CONTEXTOS_VALIDOS
from app.schemas.document_template import VariableInfo
from app.services.document_template_service import (
    VARIABLES_POR_CONTEXTO,
    obtener_variables_contexto,
)

TIPOS_SOPORTADOS = {"text", "number", "date", "boolean", "image", "table"}


def test_todo_contexto_valido_tiene_variables_registradas():
    faltantes = [c for c in CONTEXTOS_VALIDOS if c not in VARIABLES_POR_CONTEXTO]
    assert faltantes == []


def test_no_hay_variables_para_contextos_inexistentes():
    huerfanos = [c for c in VARIABLES_POR_CONTEXTO if c not in CONTEXTOS_VALIDOS]
    assert huerfanos == []


def test_todas_las_variables_usan_un_tipo_soportado_por_pdfme():
    invalidas = [
        (contexto, var.nombre, var.tipo)
        for contexto, variables in VARIABLES_POR_CONTEXTO.items()
        for var in variables
        if var.tipo not in TIPOS_SOPORTADOS
    ]
    assert invalidas == []


def test_contexto_horarios_empleado_expone_header_totales_y_la_tabla():
    variables = obtener_variables_contexto("horarios_empleado")
    assert variables is not None

    por_nombre: dict[str, VariableInfo] = {v.nombre: v for v in variables}

    esperadas = {
        "legajo",
        "nombre_completo",
        "dni",
        "cuil",
        "puesto",
        "area",
        "periodo",
        "total_horas",
        "total_dias",
        "tabla_dias",
    }
    assert esperadas <= set(por_nombre)

    # Los días son una tabla pdfme, no texto.
    assert por_nombre["tabla_dias"].tipo == "table"

    # UNA sola tabla: dos tablas es la forma que rompía en producción, porque
    # pdfme apila las tablas en un único flujo vertical y la segunda terminaba
    # montada sobre el encabezado.
    assert [v.nombre for v in variables if v.tipo == "table"] == ["tabla_dias"]
