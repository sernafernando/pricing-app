"""Unit tests del servicio de adjuntos polimórficos (Batch H).

Se testea en aislado la lógica de validación (magic bytes + tamaño) sin
persistir a DB. Tests de integración de los endpoints viven en
`tests/integration/test_compras_adjuntos_endpoints.py`.
"""

from __future__ import annotations

import pytest

from app.services.compras_adjuntos_service import _validate_magic_compras


class TestValidateMagicCompras:
    """Whitelist de formatos permitidos en compras (decisión usuario)."""

    def test_acepta_pdf(self) -> None:
        content = b"%PDF-1.4\n" + b"\x00" * 10
        assert _validate_magic_compras(content, "factura.pdf") is True

    def test_acepta_jpeg(self) -> None:
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        assert _validate_magic_compras(content, "foto.jpg") is True

    def test_acepta_png(self) -> None:
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        assert _validate_magic_compras(content, "captura.png") is True

    def test_acepta_webp(self) -> None:
        content = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 10
        assert _validate_magic_compras(content, "web.webp") is True

    def test_acepta_docx_xlsx_zip(self) -> None:
        # Tanto DOCX como XLSX son contenedores ZIP — mismo magic.
        content = b"PK\x03\x04" + b"\x00" * 20
        assert _validate_magic_compras(content, "presupuesto.docx") is True
        assert _validate_magic_compras(content, "planilla.xlsx") is True

    def test_acepta_doc_xls_legacy_ole2(self) -> None:
        # DOC y XLS legacy comparten el header OLE2.
        content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20
        assert _validate_magic_compras(content, "viejo.doc") is True
        assert _validate_magic_compras(content, "viejo.xls") is True

    def test_rechaza_webp_sin_marcador_webp(self) -> None:
        # RIFF sin "WEBP" en offset 8 (podría ser AVI, WAV, etc.)
        content = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"\x00" * 10
        assert _validate_magic_compras(content, "video.webp") is False

    @pytest.mark.parametrize(
        "content",
        [
            b"MZ\x90\x00" + b"\x00" * 20,  # EXE (PE)
            b"\x7fELF" + b"\x00" * 20,  # ELF linux
            b"<?xml version" + b"\x00" * 10,  # XML crudo / SVG
            b"<!DOCTYPE html>",  # HTML
            b"\x00\x00\x00",  # garbage
        ],
    )
    def test_rechaza_formatos_no_permitidos(self, content: bytes) -> None:
        assert _validate_magic_compras(content, "x.pdf") is False

    def test_rechaza_archivo_muy_chico(self) -> None:
        # <8 bytes = imposible verificar magic → rechazar
        assert _validate_magic_compras(b"%PDF", "x.pdf") is False

    def test_rechaza_extension_manipulada_con_contenido_falso(self) -> None:
        """Nombre .pdf pero contenido es EXE → rechaza."""
        content = b"MZ\x90\x00" + b"\x00" * 20
        assert _validate_magic_compras(content, "factura.pdf") is False
