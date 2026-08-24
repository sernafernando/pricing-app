"""Normalization parameters for the Tienda Nube image normalizer.

Pure data + a deterministic fingerprint. No I/O, no ORM.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

FINGERPRINT_LENGTH = 32
FINGERPRINT_VERSION = "v1"


@dataclass(frozen=True)
class NormalizationParams:
    """Immutable set of parameters for a single normalization run.

    Attributes:
        preset: target square canvas size in pixels (one of 800, 1080, 1200).
        fill_color: opaque hex color used to pad/flatten (e.g. "#ffffff").
        output_format: output image format identifier (e.g. "jpeg").
        quality: initial JPEG quality (0-100) before the size ladder retries.
        max_output_bytes: maximum allowed encoded output size in bytes.
    """

    preset: int
    fill_color: str
    output_format: str
    quality: int
    max_output_bytes: int


def params_fingerprint(params: NormalizationParams) -> str:
    """Compute a deterministic, ordered fingerprint of the normalization params.

    The key order is fixed (preset, fill, fmt, quality, maxbytes), NOT
    dependent on dict iteration order, so the fingerprint is stable and
    reproducible across processes and Python versions.
    """
    canonical = (
        f"{FINGERPRINT_VERSION}"
        f"|preset={params.preset}"
        f"|fill={params.fill_color}"
        f"|fmt={params.output_format}"
        f"|q={params.quality}"
        f"|maxbytes={params.max_output_bytes}"
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]
