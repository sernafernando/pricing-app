"""Unit tests for OC-match MIME classify and Office-still-valid adjuntos."""

from __future__ import annotations

from pathlib import Path

from app.services.compras_adjuntos_service import _validate_magic_compras
from app.services.oc_match.mime import KIND_GEMINI, KIND_OFFICE, KIND_UNKNOWN, classify

_ROUTER = Path(__file__).resolve().parents[2] / "app" / "routers" / "administracion_compras.py"
_MIME = Path(__file__).resolve().parents[2] / "app" / "services" / "oc_match" / "mime.py"


def _pdf() -> bytes:
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


def _jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 12


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _webp() -> bytes:
    return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 4


def _ooxml() -> bytes:
    return b"PK\x03\x04" + b"\x00" * 20


def _ole2() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8


class TestClassifyGemini:
    def test_pdf_magic(self) -> None:
        assert classify("proforma.pdf", _pdf()) == KIND_GEMINI

    def test_jpeg_magic(self) -> None:
        assert classify("scan.jpg", _jpeg()) == KIND_GEMINI

    def test_jpeg_suffix_jpeg(self) -> None:
        assert classify("scan.jpeg", _jpeg()) == KIND_GEMINI

    def test_png_magic(self) -> None:
        assert classify("foto.png", _png()) == KIND_GEMINI

    def test_webp_magic(self) -> None:
        assert classify("foto.webp", _webp()) == KIND_GEMINI

    def test_pdf_suffix_wins_when_magic_short(self) -> None:
        assert classify("proforma.pdf", b"xx") == KIND_GEMINI


class TestClassifyOffice:
    def test_xlsx_ooxml(self) -> None:
        assert classify("carga.xlsx", _ooxml()) == KIND_OFFICE

    def test_docx_ooxml(self) -> None:
        assert classify("nota.docx", _ooxml()) == KIND_OFFICE

    def test_xls_ole2(self) -> None:
        assert classify("viejo.xls", _ole2()) == KIND_OFFICE

    def test_doc_ole2(self) -> None:
        assert classify("viejo.doc", _ole2()) == KIND_OFFICE

    def test_ooxml_with_pdf_suffix_is_office(self) -> None:
        assert classify("mentira.pdf", _ooxml()) == KIND_OFFICE


class TestClassifyUnknown:
    def test_empty_is_unknown(self) -> None:
        assert classify("archivo.bin", b"") == KIND_UNKNOWN

    def test_random_bytes_unknown(self) -> None:
        assert classify("notes.txt", b"hello world!!!!") == KIND_UNKNOWN


class TestOfficeRemainsValidAdjunto:
    def test_xlsx_magic_accepted(self) -> None:
        assert _validate_magic_compras(_ooxml(), "carga.xlsx") is True

    def test_docx_magic_accepted(self) -> None:
        assert _validate_magic_compras(_ooxml(), "nota.docx") is True

    def test_xls_ole2_accepted(self) -> None:
        assert _validate_magic_compras(_ole2(), "viejo.xls") is True


class TestZeroGeminiAndHookUnwired:
    def test_mime_source_has_no_gemini_client(self) -> None:
        source = _MIME.read_text(encoding="utf-8")
        assert "google.genai" not in source
        assert "GEMINI_API_KEY" not in source

    def test_compras_router_does_not_import_oc_match(self) -> None:
        source = _ROUTER.read_text(encoding="utf-8")
        assert "oc_match" not in source
        assert "run_oc_match" not in source
        assert "google.genai" not in source
