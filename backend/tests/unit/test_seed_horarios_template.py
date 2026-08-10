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
