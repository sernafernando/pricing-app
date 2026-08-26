"""Normalization parameters for the Tienda Nube image normalizer.

Pure data + a deterministic fingerprint. No I/O, no ORM.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

FINGERPRINT_LENGTH = 32
FINGERPRINT_VERSION = "v1"

# Supported square canvas sizes, ascending. Lives here rather than in the
# engine because it is the domain of a PARAMETER: the dataclass is the gate
# that keeps an unsupported preset from ever reaching the engine.
PRESETS: tuple[int, ...] = (800, 1080, 1200)

# Full-length opaque hex only. The engine slices this in byte pairs, so CSS
# shorthand ("#fff") and named colors ("white") are not merely unsupported,
# they decode into garbage or raise mid-pipeline.
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


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

    def __post_init__(self) -> None:
        """Reject anything the engine cannot honor.

        `normalize_image` documents itself as a pure function that never
        raises: every outcome travels through `NormalizationResult.outcome`.
        That promise only holds if the parameters are known-good before the
        engine runs, so validation belongs here and nowhere else.
        """
        if self.preset not in PRESETS:
            raise ValueError(f"preset must be one of {PRESETS}, got {self.preset!r}")
        if not _HEX_COLOR_RE.match(self.fill_color):
            raise ValueError(f"fill_color must be full-length opaque hex like '#ffffff', got {self.fill_color!r}")
        if not 1 <= self.quality <= 100:
            raise ValueError(f"quality must be between 1 and 100, got {self.quality!r}")
        if self.max_output_bytes <= 0:
            raise ValueError(f"max_output_bytes must be positive, got {self.max_output_bytes!r}")


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
