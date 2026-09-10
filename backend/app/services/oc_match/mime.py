"""
Classify pedido adjuntos for OC-match Gemini eligibility.

PDF / JPG / JPEG / PNG / WEBP → gemini (enqueue later).
Office (DOCX/XLSX/DOC/XLS) and unknown → office | unknown (skip Gemini).

Classification uses magic bytes first, then filename suffix. This module
does not reject uploads — `compras_adjuntos_service` keeps Office valid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

KIND_GEMINI: Literal["gemini"] = "gemini"
KIND_OFFICE: Literal["office"] = "office"
KIND_UNKNOWN: Literal["unknown"] = "unknown"

OcMatchMimeKind = Literal["gemini", "office", "unknown"]

_GEMINI_SUFFIXES: frozenset[str] = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".webp"})
_OFFICE_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".xlsm", ".xls", ".docx", ".doc"})

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _suffix(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def _kind_from_magic(content: bytes) -> Optional[OcMatchMimeKind]:
    if len(content) < 8:
        return None
    header = content[:16]
    if header.startswith(b"%PDF"):
        return KIND_GEMINI
    if header.startswith(b"\xff\xd8\xff"):
        return KIND_GEMINI
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return KIND_GEMINI
    if header[:4] == b"RIFF" and len(content) >= 12 and content[8:12] == b"WEBP":
        return KIND_GEMINI
    if header.startswith(b"PK\x03\x04"):
        return KIND_OFFICE
    if header.startswith(_OLE2):
        return KIND_OFFICE
    return None


def _kind_from_suffix(filename: str) -> Optional[OcMatchMimeKind]:
    suffix = _suffix(filename)
    if suffix in _GEMINI_SUFFIXES:
        return KIND_GEMINI
    if suffix in _OFFICE_SUFFIXES:
        return KIND_OFFICE
    return None


def classify(
    filename: str,
    content: bytes,
    content_type: Optional[str] = None,
) -> OcMatchMimeKind:
    """
    Return ``gemini``, ``office``, or ``unknown``.

    ``content_type`` is informational (browser-supplied) and never overrides
    magic bytes. Office ZIP (PK) with a Gemini suffix still classifies as
    office — the container is not a PDF/image.
    """
    del content_type
    magic = _kind_from_magic(content)
    suffix_kind = _kind_from_suffix(filename)
    if magic == KIND_GEMINI:
        return KIND_GEMINI
    if magic == KIND_OFFICE:
        return KIND_OFFICE
    if suffix_kind is not None:
        return suffix_kind
    return KIND_UNKNOWN
