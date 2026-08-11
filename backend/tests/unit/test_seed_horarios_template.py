"""Forma del template pdfme del registro de horarios.

El PDF se arma en el navegador, así que acá no se renderiza nada: se verifica
el contrato que pdfme v5 exige (padding/borderWidth como objetos), que existan
los campos que el frontend rellena, y que el documento declare UNA sola tabla.

Lo que sí se renderiza está del otro lado: `frontend/src/utils/
horariosTemplateRender.test.js` genera un PDF real contra el fixture que este
módulo mantiene sincronizado.
"""

from __future__ import annotations

import pytest

from app.scripts.seed_document_templates import A4_H, A4_W, CONTENT_W, MARGIN
from app.scripts.seed_horarios_template import (
    FIXTURE_PATH,
    FIXTURE_REGEN_CMD,
    LINE_COLOR,
    TABLE_H,
    TABLE_HEAD,
    TABLE_W,
    TEMPLATE_HORARIOS,
    serializar_fixture,
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
        "tabla_dias",
    }
    assert esperados <= set(campos)


def test_los_campos_del_template_coinciden_con_las_variables_del_contexto(campos):
    """Todo campo no interno (`__x__`) debe existir en el registro de variables."""
    from app.services.document_template_service import obtener_variables_contexto

    variables = {v.nombre for v in obtener_variables_contexto(TEMPLATE_HORARIOS["contexto"])}
    rellenables = {n for n in campos if not n.startswith("__")}

    assert rellenables <= variables, sorted(rellenables - variables)


def test_declara_exactamente_UNA_tabla(template):
    """Regresión de producción: DOS tablas en el mismo `y` es la forma que rompe.

    pdfme modela la página como un único flujo vertical: `processDynamicPage`
    recorre las tablas acumulando un `totalYOffset` y ubica cada una en
    `baseY + totalYOffset`. Con dos tablas arrancando en el mismo `y`, la
    segunda hereda el desplazamiento de la primera y sube; contra
    @pdfme/generator 5.5.10 eso además revienta con
    `TypeError: Cannot read properties of undefined (reading 'push')` en
    `placeRowsOnPages`. Por eso el tope es UNA tabla, no "tablas que no se
    solapen".
    """
    tablas = [f for f in template["schemas"][0] if f["type"] == "table"]

    assert [t["name"] for t in tablas] == ["tabla_dias"]


def test_la_tabla_ocupa_el_ancho_util_completo(campos):
    tabla = campos["tabla_dias"]

    assert tabla["width"] == TABLE_W == CONTENT_W
    assert tabla["position"]["x"] == MARGIN
    assert tabla["position"]["x"] + tabla["width"] == MARGIN + CONTENT_W


def test_la_tabla_arranca_debajo_del_encabezado(campos):
    """Ningún campo del encabezado puede terminar por debajo del techo de la tabla.

    Es la versión estática del bug: en producción la tabla terminaba montada
    sobre el encabezado. El render real lo verifica del lado del frontend; acá
    se congela la premisa de que el schema declarado deja la banda libre.
    """
    techo_tabla = campos["tabla_dias"]["position"]["y"]
    encabezado = [f for f in campos.values() if f["position"]["y"] < techo_tabla]

    assert encabezado, "el encabezado no puede quedar vacío"
    assert max(f["position"]["y"] + f["height"] for f in encabezado) <= techo_tabla


def test_la_tabla_cumple_el_contrato_de_pdfme_v5(campos):
    tabla = campos["tabla_dias"]

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


def test_el_pie_fluye_pegado_a_la_tabla(campos):
    """Totales, firmas y fecha de emisión van DESPUÉS de la tabla, en ese orden.

    pdfme recalcula el alto de la tabla y desplaza todo lo que va debajo, así
    que el pie no puede estar clavado al margen inferior: si lo estuviera, se
    caería a una segunda página apenas la tabla creciera unos milímetros.
    """
    fondo_tabla = campos["tabla_dias"]["position"]["y"] + TABLE_H
    y_totales = campos["total_horas"]["position"]["y"]
    y_firma = campos["__firma_linea_0__"]["position"]["y"]
    y_emision = campos["fecha_emision"]["position"]["y"]

    assert fondo_tabla < y_totales < y_firma < y_emision
    # El pie termina MUY por encima del margen inferior: ese aire es lo que
    # absorbe el crecimiento de la tabla sin desbordar a otra página.
    assert y_emision + campos["fecha_emision"]["height"] < A4_H - MARGIN


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


def test_el_fixture_del_frontend_esta_al_dia():
    """El fixture commiteado tiene que ser byte a byte lo que emite este seed.

    Es el único punto de sincronización entre el builder Python y el test de
    render JS. Sin esto los dos lados divergen en silencio: el seed cambia, el
    fixture queda viejo, y el test de render sigue verde validando un template
    que ya no es el que se manda a producción.
    """
    assert FIXTURE_PATH.is_file(), f"Falta el fixture {FIXTURE_PATH}. Regeneralo con:\n  {FIXTURE_REGEN_CMD}"

    assert FIXTURE_PATH.read_text(encoding="utf-8") == serializar_fixture(), (
        f"El fixture {FIXTURE_PATH.name} quedó desactualizado respecto de "
        f"`template_horarios()`. Regeneralo con:\n  {FIXTURE_REGEN_CMD}"
    )
