"""Forma del template pdfme del registro de horarios.

El PDF se arma en el navegador, así que acá no se renderiza nada: se verifica
el contrato que pdfme v5 exige (padding/borderWidth como objetos), que existan
los campos que el frontend rellena, y que la geometría fija de las dos tablas
no se pise entre sí ni se salga de la hoja.
"""

from __future__ import annotations

import pytest

from app.scripts.seed_document_templates import A4_H, A4_W, CONTENT_W, MARGIN
from app.scripts.seed_horarios_template import (
    LINE_COLOR,
    TABLE_GAP,
    TABLE_H,
    TABLE_HEAD,
    TABLE_W,
    TEMPLATE_HORARIOS,
    template_horarios,
)


@pytest.fixture(scope="module")
def template() -> dict:
    return template_horarios()


@pytest.fixture(scope="module")
def campos(template) -> dict[str, dict]:
    return {f["name"]: f for f in template["schemas"][0]}


def test_es_una_sola_pagina_A4_vertical(template):
    assert template["basePdf"] == {
        "width": A4_W,
        "height": A4_H,
        "padding": [MARGIN, MARGIN, MARGIN, MARGIN],
    }
    assert len(template["schemas"]) == 1


def test_expone_los_campos_que_llena_el_frontend(campos):
    esperados = {
        "nombre_completo",
        "legajo",
        "dni",
        "cuil",
        "puesto",
        "area",
        "periodo",
        "fecha_emision",
        "total_horas",
        "total_dias",
        "tabla_dias_1",
        "tabla_dias_2",
    }
    assert esperados <= set(campos)


def test_los_campos_del_template_coinciden_con_las_variables_del_contexto(campos):
    """Todo campo no interno (`__x__`) debe existir en el registro de variables."""
    from app.services.document_template_service import obtener_variables_contexto

    variables = {v.nombre for v in obtener_variables_contexto(TEMPLATE_HORARIOS["contexto"])}
    rellenables = {n for n in campos if not n.startswith("__")}

    assert rellenables <= variables, sorted(rellenables - variables)


@pytest.mark.parametrize("nombre", ["tabla_dias_1", "tabla_dias_2"])
def test_las_tablas_cumplen_el_contrato_de_pdfme_v5(campos, nombre):
    tabla = campos[nombre]

    assert tabla["type"] == "table"
    assert tabla["head"] == TABLE_HEAD
    assert sum(tabla["headWidthPercentages"]) == 100
    assert len(tabla["headWidthPercentages"]) == len(TABLE_HEAD)

    # pdfme v5 rompe si `padding` / `borderWidth` son escalares.
    for estilos in (tabla["headStyles"], tabla["bodyStyles"]):
        assert set(estilos["padding"]) == {"top", "right", "bottom", "left"}
        assert set(estilos["borderWidth"]) == {"top", "right", "bottom", "left"}

    assert "tableStyles" in tabla
    assert "columnStyles" in tabla


def test_las_dos_tablas_van_lado_a_lado_sin_solaparse(campos):
    izq, der = campos["tabla_dias_1"], campos["tabla_dias_2"]

    assert izq["position"]["y"] == der["position"]["y"]
    assert der["position"]["x"] == izq["position"]["x"] + TABLE_W + TABLE_GAP
    # Ambas entran en el ancho útil de la hoja.
    assert der["position"]["x"] + TABLE_W == MARGIN + CONTENT_W


def test_los_totales_quedan_debajo_de_las_tablas_y_arriba_de_las_firmas(campos):
    fondo_tabla = campos["tabla_dias_1"]["position"]["y"] + TABLE_H
    y_totales = campos["total_horas"]["position"]["y"]
    y_firma = campos["__firma_linea_0__"]["position"]["y"]

    assert fondo_tabla < y_totales < y_firma
    assert y_firma + campos["__firma_label_0__"]["height"] < A4_H


@pytest.mark.parametrize("nombre", ["__linea_header__", "__firma_linea_0__", "__firma_linea_1__"])
def test_las_lineas_usan_el_tipo_line_real_y_no_un_texto_con_fondo(campos, nombre):
    """Regresión: el helper base dibuja las líneas como campos `text` de 0.3mm
    con `backgroundColor` y `fontSize: 1`, un workaround previo a que el plugin
    `line` estuviera habilitado. Hoy `line` está en `pdfmePlugins.js` y el
    template de sanciones ya usa el tipo real; si alguien vuelve a importar
    `_header_block` / `_firma_block` del seed base, esto lo frena.
    """
    campo = campos[nombre]

    assert campo["type"] == "line"
    assert "color" in campo
    assert "backgroundColor" not in campo


def test_el_header_lleva_logo_y_linea_corporativa(campos):
    """El documento se entrega en mano con el recibo: sin membrete parece una
    planilla suelta en vez de un documento de la empresa.
    """
    logo = campos["__logo__"]
    assert logo["type"] == "image"
    # Vacío a propósito: se carga desde el Diseñador y queda persistido ahí.
    assert logo["content"] == ""

    # Mismo azul corporativo que el template de sanciones.
    assert campos["__linea_header__"]["color"] == LINE_COLOR


def test_la_fecha_de_emision_va_al_pie_sin_pisar_las_firmas(campos):
    y_label_firma = campos["__firma_label_0__"]["position"]["y"]
    emision = campos["fecha_emision"]

    assert y_label_firma < emision["position"]["y"]
    assert emision["position"]["y"] + emision["height"] <= A4_H - MARGIN
