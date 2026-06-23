"""
Tests for zpl_label_home_service — pure transform, zip extraction, filename derivation.

TDD: These tests were written BEFORE the implementation (strict TDD mode).
"""

import io
import zipfile

import pytest

from app.services.zpl_label_home_service import (
    AmbiguousZipError,
    BadZipError,
    NoLabelHomeError,
    NoTxtInZipError,
    RewriteResult,
    derive_output_filename,
    extract_inner_txt,
    rewrite_label_home,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_zpl(lh: str = "^LH5,15", extra: str = "") -> bytes:
    """Build a minimal single-label ZPL fixture around a given ^LH command."""
    return (f"^XA\n{lh}\n^FO10,10^ADN,18,10^FDTest^FS\n{extra}^XZ\n").encode("ascii")


def make_zpl_bytes(lh: bytes = b"^LH5,15", extra: bytes = b"") -> bytes:
    """Build a minimal ZPL fixture using raw bytes (for multibyte tests)."""
    return b"^XA\n" + lh + b"\n^FO10,10^ADN,18,10^FDTest^FS\n" + extra + b"^XZ\n"


def make_zip_with_files(files: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP containing the provided filename→bytes mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ── rewrite_label_home: basic rewrites ───────────────────────────────────────


class TestRewriteLabelHome:
    def test_s01_default_y_450_single_lh(self):
        """S01: Default Y=450, single ^LH5,15 → ^LH5,450, x=5 preserved, lh_modified=1."""
        raw = make_zpl("^LH5,15")
        result = rewrite_label_home(raw, 450)

        assert isinstance(result, RewriteResult)
        assert b"^LH5,450" in result.content
        assert b"^LH5,15" not in result.content
        assert result.lh_modified == 1

    def test_s02_custom_y_300(self):
        """S02: Custom Y=300 → ^LH5,300."""
        raw = make_zpl("^LH5,15")
        result = rewrite_label_home(raw, 300)

        assert b"^LH5,300" in result.content
        assert result.lh_modified == 1

    def test_s03_x_preservation_non_default(self):
        """S03: Non-default x=7 → ^LH7,450 (x preserved from group 1)."""
        raw = make_zpl("^LH7,15")
        result = rewrite_label_home(raw, 450)

        assert b"^LH7,450" in result.content
        assert b"^LH5,450" not in result.content

    def test_s04_multi_label_all_rewritten(self):
        """S04/S05: Multi-label file — all ^LH rewritten, counts correct."""
        # Build a 10-label fixture (smaller synthetic equivalent of 330)
        label_block = b"^XA\n^LH5,15\n^FDTest^FS\n^XZ\n"
        raw = label_block * 10

        result = rewrite_label_home(raw, 450)

        assert result.lh_modified == 10
        assert result.labels_detected == 10
        assert b"^LH5,15" not in result.content
        assert result.content.count(b"^LH5,450") == 10

    def test_s06_ec1_no_lh_raises(self):
        """S06/EC1: No ^LH in file → raises NoLabelHomeError."""
        raw = b"^XA\n^FO10,10^ADN,18,10^FDTest^FS\n^XZ\n"

        with pytest.raises(NoLabelHomeError):
            rewrite_label_home(raw, 450)

    def test_ec1_empty_bytes_raises(self):
        """EC1: Empty bytes input → raises NoLabelHomeError."""
        with pytest.raises(NoLabelHomeError):
            rewrite_label_home(b"", 450)

    def test_s10_heterogeneous_y_values(self):
        """S10: Heterogeneous y values → heterogeneous=True, both normalized to target."""
        raw = b"^XA\n^LH5,10\n^FDLabel1^FS\n^XZ\n^XA\n^LH5,20\n^FDLabel2^FS\n^XZ\n"
        result = rewrite_label_home(raw, 450)

        assert result.heterogeneous is True
        assert result.content.count(b"^LH5,450") == 2
        assert b"^LH5,10" not in result.content
        assert b"^LH5,20" not in result.content

    def test_s10_homogeneous_y_values(self):
        """Homogeneous y values → heterogeneous=False."""
        raw = b"^XA\n^LH5,15\n^FDLabel1^FS\n^XZ\n^XA\n^LH5,15\n^FDLabel2^FS\n^XZ\n"
        result = rewrite_label_home(raw, 450)

        assert result.heterogeneous is False

    def test_s16_s17_byte_identity_outside_lh(self):
        """S16/S17: All bytes outside ^LH spans are byte-identical to input."""
        lh_tag = b"^LH5,15"
        prefix = b"^XA\n"
        suffix = b"\n^FO10,10^ADN,18,10^FDTest^FS\n^XZ\n"
        raw = prefix + lh_tag + suffix

        result = rewrite_label_home(raw, 450)

        # Split on any ^LH occurrence in output and check surrounding content
        assert result.content.startswith(prefix)
        assert result.content.endswith(suffix)

    def test_s17_lf_only_preserved(self):
        """S17: LF-only file stays LF-only (no CRLF introduced)."""
        raw = b"^XA\n^LH5,15\n^FDTest^FS\n^XZ\n"
        assert b"\r\n" not in raw  # sanity check

        result = rewrite_label_home(raw, 450)

        assert b"\r\n" not in result.content

    def test_s17_crlf_preserved(self):
        """S17: CRLF file stays CRLF."""
        raw = b"^XA\r\n^LH5,15\r\n^FDTest^FS\r\n^XZ\r\n"

        result = rewrite_label_home(raw, 450)

        # All line endings should still be CRLF
        assert b"\r\n" in result.content
        # No bare \n without preceding \r (every \n preceded by \r)
        content = result.content
        for i, byte_val in enumerate(content):
            if byte_val == ord("\n"):
                assert i > 0 and content[i - 1] == ord("\r"), f"Bare LF found at position {i}"

    def test_s18_ll_warning_fires_when_y_exceeds(self):
        """S18: ^LL400 + target_y=450 → ll_warning non-empty, references both values."""
        raw = b"^XA\n^LL400\n^LH5,15\n^FDTest^FS\n^XZ\n"
        result = rewrite_label_home(raw, 450)

        assert result.ll_warning != ""
        assert "450" in result.ll_warning
        assert "400" in result.ll_warning

    def test_s19_no_ll_no_warning(self):
        """S19: No ^LL present → ll_warning == ''."""
        raw = make_zpl("^LH5,15")
        result = rewrite_label_home(raw, 450)

        assert result.ll_warning == ""

    def test_s20_ll_present_y_does_not_exceed(self):
        """S20: ^LL500 + target_y=450 (450 < 500) → ll_warning == ''."""
        raw = b"^XA\n^LL500\n^LH5,15\n^FDTest^FS\n^XZ\n"
        result = rewrite_label_home(raw, 450)

        assert result.ll_warning == ""

    def test_ec2_x_zero_preserved(self):
        """EC2: x=0 → ^LH0,450 produced."""
        raw = make_zpl("^LH0,15")
        result = rewrite_label_home(raw, 450)

        assert b"^LH0,450" in result.content

    def test_ec3_y_zero_valid(self):
        """EC3: Y=0 → ^LH5,0 is legal."""
        raw = make_zpl("^LH5,15")
        result = rewrite_label_home(raw, 0)

        assert b"^LH5,0" in result.content

    def test_ec4_lh_present_zero_xas(self):
        """EC4: File with ^LH but 0 ^XA → labels_detected=0, lh_modified >= 1."""
        raw = b"^LH5,15\n^FDNo XA block^FS\n"
        result = rewrite_label_home(raw, 450)

        assert result.labels_detected == 0
        assert result.lh_modified >= 1

    def test_r47_ci28_bytes_pass_through(self):
        """R4.7: Bytes with ^CI28 alongside ^LH → non-^LH bytes unchanged."""
        ci28 = b"^CI28"
        lh = b"^LH5,15"
        suffix = b"\n^FDTest^FS\n^XZ\n"
        raw = b"^XA\n" + ci28 + b"\n" + lh + suffix

        result = rewrite_label_home(raw, 450)

        # ^CI28 must be byte-identical in output
        assert ci28 in result.content
        # suffix must be byte-identical in output
        assert suffix in result.content

    def test_label_count_uses_xxa_count(self):
        """R8.1: labels_detected = count of ^XA occurrences in processed bytes."""
        # 3 labels
        raw = (b"^XA\n^LH5,15\n^FDTest^FS\n^XZ\n") * 3
        result = rewrite_label_home(raw, 450)

        assert result.labels_detected == 3


# ── extract_inner_txt ─────────────────────────────────────────────────────────


class TestExtractInnerTxt:
    def test_t41a_single_txt_selected(self):
        """T4.1a: Single .txt in zip → returns (bytes, correct stem)."""
        content = b"^XA\n^LH5,15\n^XZ\n"
        raw_zip = make_zip_with_files({"Envio-12345-Etiquetas.txt": content})

        inner, stem = extract_inner_txt(raw_zip)

        assert inner == content
        assert stem == "Envio-12345-Etiquetas"

    def test_t41b_multiple_txt_envio_selected(self):
        """T4.1b: Multiple .txt, one matching Envio-* → selects that one."""
        envio_content = b"^XA\n^LH5,15\n^XZ\n"
        raw_zip = make_zip_with_files(
            {
                "Envio-12345-Etiquetas.txt": envio_content,
                "README.txt": b"readme content",
            }
        )

        inner, stem = extract_inner_txt(raw_zip)

        assert inner == envio_content
        assert stem == "Envio-12345-Etiquetas"

    def test_t41c_multiple_envio_raises_ambiguous(self):
        """T4.1c: Multiple Envio-* matches → raises AmbiguousZipError."""
        raw_zip = make_zip_with_files(
            {
                "Envio-1-Etiquetas.txt": b"content1",
                "Envio-2-Etiquetas.txt": b"content2",
            }
        )

        with pytest.raises(AmbiguousZipError, match="múltiples archivos Envio-"):
            extract_inner_txt(raw_zip)

    def test_t41d_multiple_txt_no_envio_raises(self):
        """T4.1d: Multiple .txt, none Envio-* → raises AmbiguousZipError."""
        raw_zip = make_zip_with_files(
            {
                "labels.txt": b"content1",
                "extra.txt": b"content2",
            }
        )

        with pytest.raises(AmbiguousZipError, match="múltiples"):
            extract_inner_txt(raw_zip)

    def test_t41e_zero_txt_raises(self):
        """T4.1e: Zero .txt in zip → raises NoTxtInZipError."""
        raw_zip = make_zip_with_files({"document.pdf": b"%PDF content"})

        with pytest.raises(NoTxtInZipError):
            extract_inner_txt(raw_zip)

    def test_t41f_bad_zip_raises(self):
        """T4.1f: Bad zip bytes → raises BadZipError."""
        with pytest.raises(BadZipError):
            extract_inner_txt(b"not a zip file at all")

    def test_t41g_single_txt_not_envio_selected(self):
        """EC6/T4.1g: Single .txt not named Envio-* → selected unconditionally."""
        content = b"^XA\n^LH5,15\n^XZ\n"
        raw_zip = make_zip_with_files({"labels.txt": content})

        inner, stem = extract_inner_txt(raw_zip)

        assert inner == content
        assert stem == "labels"

    def test_t41h_macosx_entries_excluded(self):
        """T4.1h: __MACOSX entries excluded from .txt count."""
        content = b"^XA\n^LH5,15\n^XZ\n"
        raw_zip = make_zip_with_files(
            {
                "Envio-12345.txt": content,
                "__MACOSX/._Envio-12345.txt": b"macos junk",
            }
        )

        inner, stem = extract_inner_txt(raw_zip)

        # Should select the real .txt, not be confused by __MACOSX
        assert inner == content
        assert stem == "Envio-12345"


# ── derive_output_filename ────────────────────────────────────────────────────


class TestDeriveOutputFilename:
    def test_normal_stem(self):
        """Normal stem → {stem}_corregido.txt."""
        assert derive_output_filename("Envio-12345-Etiquetas-de-bultos") == (
            "Envio-12345-Etiquetas-de-bultos_corregido.txt"
        )

    def test_stem_already_corregido_no_double_suffix(self):
        """Stem already ending _corregido → {stem}.txt (no double-suffix)."""
        assert derive_output_filename("Envio-12345_corregido") == "Envio-12345_corregido.txt"

    def test_stem_with_path_separators_sanitized(self):
        """Stem with path separators → sanitized to safe chars."""
        result = derive_output_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result
        assert result.endswith(".txt")

    def test_empty_stem_fallback(self):
        """Empty stem → fallback etiqueta_corregido.txt."""
        assert derive_output_filename("") == "etiqueta_corregido.txt"

    def test_stem_with_spaces_sanitized(self):
        """Spaces in stem → replaced with underscore."""
        result = derive_output_filename("my label file")
        assert " " not in result
        assert result == "my_label_file_corregido.txt"
