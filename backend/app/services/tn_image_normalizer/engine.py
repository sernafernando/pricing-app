"""Pure image normalization engine: bytes -> normalized bytes.

Design invariants (see design doc for the full rationale):

- Always square. Padding, NEVER crop — the whole photo survives.
- Never upscale, under any circumstance.
- Presets: 800, 1080, 1200.
  - source longest edge >= preset -> downscale so the longest edge equals
    the preset, then pad to a square canvas of that preset.
  - source longest edge < preset -> step down to the nearest LOWER preset
    the source can fill.
  - source longest edge < 800 (no lower preset) -> canvas stays 800x800 and
    the photo is pasted centered at its real pixel size, unscaled.
- EXIF orientation is applied FIRST, before any measurement or resize.
- Transparency is flattened onto the fill color via the SAME composite path
  used for ordinary padding (one composite, two effects).
- Output: JPEG, quality 85 (default), progressive, 4:2:0, no alpha, sRGB,
  EXIF stripped.
- Size ladder: if the encoded output exceeds max_output_bytes, retry at
  quality 80, then 75, then 70. Still over after 70 -> TOO_LARGE outcome.

This module performs NO I/O: no filesystem, no network, no ORM. It must
never import from app.models, app.core.database, or any HTTP/DB client.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.tn_image_normalizer.params import NormalizationParams

# Fixed, ascending preset ladder. The engine only ever resolves a canvas
# size to one of these values.
PRESETS: tuple[int, ...] = (800, 1080, 1200)

# Quality ladder tried in order until the encoded output fits the budget.
QUALITY_LADDER: tuple[int, ...] = (85, 80, 75, 70)


class NormalizationOutcome(str, Enum):
    """Tagged outcome of a normalization attempt. Never a bare bool."""

    SUCCESS = "success"
    TOO_LARGE = "too_large"
    DECODE_FAILED = "decode_failed"


@dataclass(frozen=True)
class NormalizationResult:
    """Result of normalizing a single image.

    Attributes:
        outcome: what happened. SUCCESS carries output_bytes/dimensions/quality.
        output_bytes: encoded JPEG bytes, only set when outcome is SUCCESS.
        final_width: canvas width in pixels, only set when outcome is SUCCESS.
        final_height: canvas height in pixels, only set when outcome is SUCCESS.
        quality_used: the JPEG quality that produced output_bytes, only set
            when outcome is SUCCESS.
    """

    outcome: NormalizationOutcome
    output_bytes: bytes | None = None
    final_width: int | None = None
    final_height: int | None = None
    quality_used: int | None = None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _resolve_canvas_size(longest_edge: int, requested_preset: int) -> int:
    """Resolve the canvas size for a given source longest edge.

    Never upscales: if the source can fill the requested preset, use it.
    Otherwise step down to the nearest lower preset the source can fill.
    If the source is under the smallest preset, fall back to that preset
    (the caller pastes it unscaled and centered).
    """
    eligible = [preset for preset in PRESETS if preset <= longest_edge]
    if eligible:
        # Largest preset the source can fill without upscaling. If the
        # requested preset itself is eligible, prefer it over stepping down
        # further than necessary.
        if requested_preset in eligible:
            return requested_preset
        return max(eligible)
    return PRESETS[0]


def _compose_on_canvas(image: Image.Image, canvas_size: int, fill_rgb: tuple[int, int, int]) -> Image.Image:
    """Paste `image` (already sized correctly) centered onto a square canvas.

    This is the single composite path used both for ordinary padding and for
    transparency flattening: the canvas starts fully filled with the opaque
    fill color, and the source is alpha-composited on top when it carries an
    alpha channel, or pasted directly otherwise.
    """
    canvas = Image.new("RGB", (canvas_size, canvas_size), fill_rgb)
    left = (canvas_size - image.width) // 2
    top = (canvas_size - image.height) // 2

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba_image = image.convert("RGBA")
        canvas.paste(rgba_image, (left, top), rgba_image)
    else:
        canvas.paste(image.convert("RGB"), (left, top))

    return canvas


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.save(
        buf,
        format="JPEG",
        quality=quality,
        progressive=True,
        subsampling=2,  # 4:2:0
        optimize=True,
        exif=b"",
        icc_profile=None,
    )
    return buf.getvalue()


def normalize_image(source_bytes: bytes, params: NormalizationParams) -> NormalizationResult:
    """Normalize raw image bytes into a square, padded, size-bounded JPEG.

    Pure function: no I/O. Never raises for undecodable input or an
    over-budget result — both are reported via NormalizationResult.outcome.
    """
    try:
        decoded = Image.open(io.BytesIO(source_bytes))
        decoded.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return NormalizationResult(outcome=NormalizationOutcome.DECODE_FAILED)

    # EXIF orientation FIRST, before any measurement.
    upright = ImageOps.exif_transpose(decoded)
    if upright is None:
        upright = decoded

    longest_edge = max(upright.width, upright.height)
    canvas_size = _resolve_canvas_size(longest_edge, params.preset)

    if longest_edge >= canvas_size:
        # Downscale so the longest edge equals the canvas size.
        scale = canvas_size / longest_edge
        new_width = max(1, round(upright.width * scale))
        new_height = max(1, round(upright.height * scale))
        resized = upright.resize((new_width, new_height), Image.LANCZOS)
    else:
        # Source under the smallest usable preset: paste unscaled.
        resized = upright

    fill_rgb = _hex_to_rgb(params.fill_color)
    composed = _compose_on_canvas(resized, canvas_size, fill_rgb)

    ladder = (params.quality, *(q for q in QUALITY_LADDER if q < params.quality))
    for quality in ladder:
        encoded = _encode_jpeg(composed, quality)
        if len(encoded) <= params.max_output_bytes:
            return NormalizationResult(
                outcome=NormalizationOutcome.SUCCESS,
                output_bytes=encoded,
                final_width=canvas_size,
                final_height=canvas_size,
                quality_used=quality,
            )

    return NormalizationResult(outcome=NormalizationOutcome.TOO_LARGE)
