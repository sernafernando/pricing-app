"""abm-productos S12: TN's description is HTML; ML takes plain text only, so the sync stores a plain-text copy made
once on write (block tags become line breaks, list items "- ", entities decoded, tags stripped, blank lines collapsed).
"""

from __future__ import annotations

from app.services.tienda_nube_sync_shared import extract_textos, html_a_texto


def test_blocks_become_lines_lists_become_dashes_entities_are_decoded_and_tags_dropped() -> None:
    html = (
        "<p>Notebook <strong>Lenovo</strong> V15 G5</p>"
        "<ul><li>Procesador Intel&reg; Core&trade; i7-13620H</li><li>16&nbsp;GB DDR5</li></ul>"
        "<p>Pantalla 15,6&quot; FHD<br>Garant&iacute;a 12 meses</p>"
    )

    assert html_a_texto(html) == (
        "Notebook Lenovo V15 G5\n"
        "- Procesador Intel® Core™ i7-13620H\n"
        "- 16 GB DDR5\n"
        'Pantalla 15,6" FHD\n'
        "Garantía 12 meses"
    )


def test_blank_lines_collapse_to_one_and_script_or_style_content_is_dropped() -> None:
    html = "<div>Uno</div><p></p><p>&nbsp;</p><style>p{color:red}</style><h3>Dos</h3><script>alert(1)</script>"

    assert html_a_texto(html) == "Uno\n\nDos"


def test_no_description_is_empty_text() -> None:
    assert html_a_texto(None) == ""
    assert html_a_texto("") == ""


def test_the_texts_row_takes_the_spanish_name_and_description_of_the_product() -> None:
    product = {"id": 7, "name": {"es": "Mouse UB500"}, "description": {"es": "<p>Inalámbrico</p>", "pt": "<p>x</p>"}}

    assert extract_textos(product) == {
        "product_id": 7,
        "nombre": "Mouse UB500",
        "descripcion_html": "<p>Inalámbrico</p>",
        "descripcion_texto": "Inalámbrico",
    }


def test_a_product_without_description_stores_none_not_empty_html() -> None:
    assert extract_textos({"id": 7, "name": {"es": "X"}})["descripcion_html"] is None


def test_a_self_closing_br_is_one_line_break_like_br() -> None:
    assert html_a_texto("<p>A<br/>B<br />C</p>") == "A\nB\nC"
