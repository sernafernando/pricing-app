"""Parser of GBP's "Reporte de Ventas Detalladas" and "Reporte de Ventas" PDFs (ventas por fuera from PDF, T1).

Both fixtures are invented from the layout of one real GBP pair (GRUPO GAUSS SRL, "Con Impuestos: No"; owner L10):
every text run is redrawn at its original position and size, with fake clients, client codes and salesperson
("CLIENTE PRUEBA NNN", "100NNN", "Carla Ejemplo"), invented document numbers, dates (March 2025) and amounts. Both
reports agree with each other, and the structure is the real one: the same 166 documents in both reports (104 Fc A,
54 Fc B, 6 Nc A, 2 Nd A), 7 "CHEQUE 30 D" documents with a 4% surcharge, mixed VAT, wrapped client names, a code
missing from productos_erp and manual lines. The real files never enter the repository.
The detailed report is the source of the lines (S3); the summary is the control, and the only one that carries the
condition of sale, so the 4% surcharge of "CHEQUE 30 D" documents comes from it (S12).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ventas_fuera_pdf.parser import ReporteInvalido, parse_detallada, parse_resumen

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ventas_fuera_pdf"
DETALLADA = FIXTURES / "gbp_detallada_anonimizada.pdf"
RESUMEN = FIXTURES / "gbp_resumen_anonimizado.pdf"


@pytest.fixture(scope="module")
def detallada():
    return parse_detallada(DETALLADA.read_bytes())


@pytest.fixture(scope="module")
def resumen():
    return parse_resumen(RESUMEN.read_bytes())


def _doc(reporte, tipo: str, letra: str, pv: int, numero: int):
    return next(
        d for d in reporte.documentos if (d.tipo, d.letra, d.punto_venta, d.numero) == (tipo, letra, pv, numero)
    )


class TestDetallada:
    def test_header_carries_company_salesperson_and_range(self, detallada) -> None:
        assert detallada.empresa == "GRUPO GAUSS SRL"
        assert detallada.vendedor == "Carla Ejemplo"
        assert (detallada.desde, detallada.hasta) == (date(2025, 3, 1), date(2025, 3, 31))

    def test_reads_the_166_documents_by_type_and_letter(self, detallada) -> None:
        tipos = Counter((d.tipo, d.letra) for d in detallada.documentos)

        assert len(detallada.documentos) == 166
        assert tipos == {("Fc", "A"): 104, ("Fc", "B"): 54, ("Nc", "A"): 6, ("Nd", "A"): 2}

    def test_line_prices_add_up_to_the_grand_total_but_for_gbp_rounding(self, detallada) -> None:
        """GBP prints every line rounded to cents but adds the unrounded amounts, so its grand total ends a few cents
        above the printed lines (0.07 in the real report, kept in the fixture). The stored lines are the printed
        ones, so their sum is 169,632,759.59, not the printed 169,632,759.66."""
        total = sum((linea.precio for d in detallada.documentos for linea in d.lineas), Decimal("0"))

        assert detallada.total_impreso == Decimal("169632759.66")
        assert total == Decimal("169632759.59")
        assert sum((linea.cantidad for d in detallada.documentos for linea in d.lineas), Decimal("0")) == Decimal(
            "1359.00"
        )

    def test_a_document_keeps_its_header_and_lines(self, detallada) -> None:
        doc = _doc(detallada, "Fc", "A", 8, 17982)

        assert doc.cliente == "CLIENTE PRUEBA 055"
        assert doc.vendedor == "Carla Ejempl"
        assert (doc.fecha, doc.fecha_vencimiento) == (date(2025, 3, 13), date(2025, 3, 13))
        assert (doc.importe, doc.saldo) == (Decimal("1472379.48"), Decimal("0.00"))
        assert [(ln.codigo, ln.articulo, ln.cantidad, ln.moneda) for ln in doc.lineas] == [
            ("198154111069", "NB LENOVO V15 G4 AMN R5-7520U 16GB D5 512GB S", Decimal("1.00"), "ARS"),
            (None, "Servicio Tecnico (Manual)", Decimal("1.00"), "ARS"),
        ]
        assert [(ln.precio, ln.precio_costo, ln.precio_costo_pp) for ln in doc.lineas] == [
            (Decimal("1198000.66"), Decimal("1106663.18"), Decimal("1135399.28")),
            (Decimal("20632.29"), Decimal("0.00"), Decimal("0.00")),
        ]

    def test_credit_notes_are_negative(self, detallada) -> None:
        nc = _doc(detallada, "Nc", "A", 8, 71846)

        assert (nc.importe, nc.saldo) == (Decimal("-38275.48"), Decimal("-38275.48"))
        assert [(ln.cantidad, ln.precio, ln.precio_costo, ln.precio_costo_pp) for ln in nc.lineas] == [
            (Decimal("-1.00"), Decimal("-34638.44"), Decimal("-29374.55"), Decimal("-30345.06"))
        ]
        assert all(ln.precio < 0 for d in detallada.documentos if d.tipo == "Nc" for ln in d.lineas)

    def test_repeated_lines_of_one_document_are_all_kept(self, detallada) -> None:
        nc = _doc(detallada, "Nc", "A", 8, 71842)

        assert [ln.codigo for ln in nc.lineas].count("1612100026553") >= 3

    def test_rejects_a_pdf_that_is_not_the_detailed_report(self) -> None:
        with pytest.raises(ReporteInvalido):
            parse_detallada(RESUMEN.read_bytes())

    def test_rejects_a_document_printed_twice_naming_it(self) -> None:
        """The first page printed twice repeats its documents; loading it would be ambiguous (verifier advisory a)."""
        with pytest.raises(ReporteInvalido, match=r"Fc A 00008-00018011 aparece más de una vez"):
            parse_detallada((FIXTURES / "gbp_detallada_documento_repetido.pdf").read_bytes())

    def test_rejects_a_truncated_pdf(self) -> None:
        contenido = DETALLADA.read_bytes()

        with pytest.raises(ReporteInvalido):
            parse_detallada(contenido[: len(contenido) // 3])

    def test_rejects_bytes_that_are_not_a_pdf(self) -> None:
        with pytest.raises(ReporteInvalido):
            parse_detallada(b"not a pdf")


class TestResumen:
    def test_header_carries_company_salesperson_and_range(self, resumen) -> None:
        assert resumen.empresa == "GRUPO GAUSS SRL"
        assert resumen.vendedor == "Carla Ejemplo"
        assert (resumen.desde, resumen.hasta) == (date(2025, 3, 1), date(2025, 3, 31))
        assert resumen.con_impuestos is False

    def test_reads_the_166_documents_with_their_totals(self, resumen) -> None:
        assert len(resumen.documentos) == 166
        assert sum((d.importe for d in resumen.documentos), Decimal("0")) == Decimal("170113150.50")
        assert sum((d.saldo for d in resumen.documentos), Decimal("0")) == Decimal("84671927.60")
        assert (resumen.total_impreso, resumen.saldo_impreso) == (Decimal("170113150.50"), Decimal("84671927.60"))

    def test_a_document_carries_client_code_and_condition_of_sale(self, resumen) -> None:
        doc = _doc(resumen, "Fc", "A", 8, 18054)

        assert (doc.cliente_codigo, doc.cliente) == ("100033", "CLIENTE PRUEBA 033")
        assert doc.condicion_venta == "CHEQUE 30 D"
        assert (doc.fecha, doc.fecha_vencimiento) == (date(2025, 3, 16), date(2025, 4, 15))
        assert (doc.importe, doc.saldo) == (Decimal("6863330.70"), Decimal("7583980.42"))

    def test_a_client_name_wrapped_over_lines_is_joined(self, resumen) -> None:
        doc = _doc(resumen, "Fc", "A", 8, 17831)

        assert (doc.cliente_codigo, doc.cliente) == ("100001", "CLIENTE PRUEBA 001")
        assert (doc.importe, doc.saldo) == (Decimal("34616.31"), Decimal("0.00"))

    def test_a_client_name_wrapped_over_four_lines_is_joined(self, resumen) -> None:
        assert any(d.cliente.endswith(" SA") and len(d.cliente.split()) == 4 for d in resumen.documentos)

    def test_seven_cheque_documents(self, resumen) -> None:
        assert sum(1 for d in resumen.documentos if d.condicion_venta == "CHEQUE 30 D") == 7

    def test_rejects_the_detailed_report(self) -> None:
        with pytest.raises(ReporteInvalido):
            parse_resumen(DETALLADA.read_bytes())
