"""
ZPL Label Home Rewriter service.

Pure, HTTP-decoupled functions for rewriting ^LH y-offset values
in ZPL label files (raw bytes, no string decoding).

Functions:
- rewrite_label_home(raw, target_y) -> RewriteResult
- extract_inner_txt(raw_zip) -> (bytes, stem)
- derive_output_filename(stem) -> str
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# ── Regex constants ──────────────────────────────────────────────────────────

# group1 = x (preserved), group2 = original y (replaced)
LH_PATTERN: re.Pattern[bytes] = re.compile(rb"\^LH(\d+),(\d+)")

# group1 = declared label length (for best-effort ^LL warning)
LL_PATTERN: re.Pattern[bytes] = re.compile(rb"\^LL(\d+)")


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class RewriteResult:
    """Result of a ^LH rewrite operation."""

    content: bytes  # full file bytes, byte-identical except ^LH y values
    labels_detected: int  # count of b"^XA" occurrences
    lh_modified: int  # number of ^LH substitutions performed
    heterogeneous: bool  # True when source ^LH y values differed before normalization
    ll_warning: str  # "" if none, else a short ASCII warning message


# ── Domain exceptions ────────────────────────────────────────────────────────


class NoLabelHomeError(Exception):
    """Raised when no ^LH command is found in the file."""


class NoTxtInZipError(Exception):
    """Raised when the ZIP contains zero .txt entries."""


class AmbiguousZipError(Exception):
    """Raised when ZIP selection is ambiguous (multiple Envio-* or multiple non-Envio- .txt)."""


class BadZipError(Exception):
    """Raised when the uploaded bytes are not a valid ZIP archive."""


# ── Pure transform ───────────────────────────────────────────────────────────


def rewrite_label_home(raw: bytes, target_y: int) -> RewriteResult:
    """Rewrite all ^LH y-values to target_y, preserving x and all other bytes.

    Args:
        raw: Raw file bytes (never decoded to str).
        target_y: New y offset to set on every ^LH command.

    Returns:
        RewriteResult with rewritten bytes and metadata.

    Raises:
        NoLabelHomeError: If no ^LH command is found in raw.
    """
    # Collect original y values before substitution to compute heterogeneity
    original_ys = [int(m.group(2)) for m in LH_PATTERN.finditer(raw)]

    if not original_ys:
        raise NoLabelHomeError(
            "No se encontró ningún comando ^LH en el archivo. Verificá que sea un archivo ZPL de etiquetas ML."
        )

    heterogeneous = len(set(original_ys)) > 1

    # Build replacement: keep group(1) (x), replace y with target_y
    target_y_bytes = str(target_y).encode("ascii")

    def _repl(m: re.Match[bytes]) -> bytes:
        return b"^LH" + m.group(1) + b"," + target_y_bytes

    content, lh_modified = LH_PATTERN.subn(_repl, raw)

    # Label count: number of ^XA occurrences in the processed bytes
    labels_detected = content.count(b"^XA")

    # Best-effort ^LL warning (only if ^LL present in file)
    ll_warning = ""
    if b"^LL" in raw:
        ll_vals = [int(v) for v in LL_PATTERN.findall(raw)]
        if ll_vals:
            min_ll = min(ll_vals)
            if target_y > min_ll:
                ll_warning = (
                    f"El offset Y ({target_y}) supera el largo de etiqueta "
                    f"declarado (^LL {min_ll}). Verificá la impresión."
                )

    return RewriteResult(
        content=content,
        labels_detected=labels_detected,
        lh_modified=lh_modified,
        heterogeneous=heterogeneous,
        ll_warning=ll_warning,
    )


# ── Zip extraction ───────────────────────────────────────────────────────────


def extract_inner_txt(raw_zip: bytes) -> tuple[bytes, str]:
    """Extract the target .txt file from a ZIP archive.

    Selection rules (R2.1–R2.5):
    - 0 .txt entries  → raise NoTxtInZipError
    - 1 .txt entry    → use it unconditionally
    - many .txt:
        - exactly 1 starts with "Envio-" → use it
        - 0 or >1 start with "Envio-"   → raise AmbiguousZipError

    Args:
        raw_zip: Raw ZIP file bytes.

    Returns:
        (inner_bytes, stem) where stem is the selected filename without .txt.

    Raises:
        BadZipError: If raw_zip is not a valid ZIP archive.
        NoTxtInZipError: If no .txt entry exists in the ZIP.
        AmbiguousZipError: If selection is ambiguous.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_zip))
    except zipfile.BadZipFile as exc:
        raise BadZipError("Archivo ZIP inválido o corrupto.") from exc

    with zf:
        all_names = zf.namelist()

        # Filter: .txt extension, skip __MACOSX and directory entries
        txt_entries = [
            n for n in all_names if n.lower().endswith(".txt") and not n.startswith("__MACOSX") and not n.endswith("/")
        ]

        if len(txt_entries) == 0:
            raise NoTxtInZipError("El archivo ZIP no contiene ningún archivo .txt.")

        if len(txt_entries) == 1:
            selected = txt_entries[0]
        else:
            # Multiple .txt: look for Envio-* matches (basename only, case-sensitive)
            envio_matches = [n for n in txt_entries if Path(n).name.startswith("Envio-")]

            if len(envio_matches) == 1:
                selected = envio_matches[0]
            elif len(envio_matches) > 1:
                raise AmbiguousZipError(
                    "El archivo ZIP contiene múltiples archivos Envio-. "
                    "Por favor, cargá un ZIP con un solo archivo de etiquetas."
                )
            else:
                raise AmbiguousZipError(
                    "El archivo ZIP contiene múltiples archivos .txt sin nombre Envio-. "
                    "Por favor, cargá el archivo .txt directamente."
                )

        inner_bytes = zf.read(selected)
        stem = Path(selected).stem

    return inner_bytes, stem


# ── Filename derivation ──────────────────────────────────────────────────────


def derive_output_filename(stem: str) -> str:
    """Derive the safe output filename from the input stem.

    Args:
        stem: Filename without extension (e.g. "Envio-12345-Etiquetas-de-bultos").

    Returns:
        Safe filename string ending in .txt (e.g. "Envio-12345-Etiquetas-de-bultos_corregido.txt").
    """
    # Sanitize: replace chars outside [A-Za-z0-9._-] with underscore
    safe_stem = re.sub(r"[^A-Za-z0-9._\-]", "_", stem)

    # Empty fallback
    if not safe_stem:
        safe_stem = "etiqueta"

    # Idempotency: avoid _corregido_corregido suffix
    if safe_stem.endswith("_corregido"):
        return f"{safe_stem}.txt"

    return f"{safe_stem}_corregido.txt"
