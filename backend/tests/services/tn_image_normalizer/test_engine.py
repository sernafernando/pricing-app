"""Tests for tn_image_normalizer.engine: pure bytes -> normalized bytes.

No I/O in the engine itself; test fixtures build small in-memory images with
Pillow directly.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageOps

from app.services.tn_image_normalizer.engine import (
    NormalizationOutcome,
    normalize_image,
)
from app.services.tn_image_normalizer.params import NormalizationParams


def _default_params(**overrides: object) -> NormalizationParams:
    base = dict(
        preset=1080,
        fill_color="#ffffff",
        output_format="jpeg",
        quality=85,
        max_output_bytes=3145728,
    )
    base.update(overrides)
    return NormalizationParams(**base)


def _encode(image: Image.Image, fmt: str = "PNG", **save_kwargs: object) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _solid_image(width: int, height: int, color: tuple[int, ...] = (255, 0, 0)) -> Image.Image:
    mode = "RGBA" if len(color) == 4 else "RGB"
    return Image.new(mode, (width, height), color)


def _corner_marked_image(width: int, height: int) -> Image.Image:
    """A distinctive image: red background with a blue top-left marker block.

    The marker is large enough (16x16) to survive JPEG 8x8-block compression
    artifacts, so orientation assertions are not flaky.
    """
    img = Image.new("RGB", (width, height), (255, 0, 0))
    marker = min(16, width, height)
    for x in range(marker):
        for y in range(marker):
            img.putpixel((x, y), (0, 0, 255))
    return img


class TestExifOrientation:
    @pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_orientation_applied_before_measurement(self, orientation: int) -> None:
        # Build a non-square image with a blue marker at the top-left corner,
        # tag it with the given EXIF orientation, and confirm the output
        # respects the *visually correct* upright orientation.
        base = _corner_marked_image(100, 60)
        exif = base.getexif()
        exif[0x0112] = orientation  # Orientation tag
        # Use a lossless PNG source so the marker's sharp edges survive
        # encoding intact; JPEG's block-based compression can bleed color
        # across the marker boundary and make pixel assertions flaky.
        buf = io.BytesIO()
        base.save(buf, format="PNG", exif=exif)
        source_bytes = buf.getvalue()

        # Compute expected upright image via exif_transpose ourselves.
        decoded = Image.open(io.BytesIO(source_bytes))
        expected_upright = ImageOps.exif_transpose(decoded)
        assert expected_upright is not None

        result = normalize_image(source_bytes, _default_params(preset=800))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.output_bytes is not None
        # The final canvas must reflect the upright aspect: since the source
        # is well under 800px on its longest edge, canvas stays 800x800 and
        # the corrected image is pasted unscaled and centered.
        out_img = Image.open(io.BytesIO(result.output_bytes))
        assert out_img.size == (800, 800)

        exp_w, exp_h = expected_upright.size
        left = (800 - exp_w) // 2
        top = (800 - exp_h) // 2

        # Locate the blue marker inside the reference upright image itself
        # (its position depends on which orientation transform was applied),
        # then confirm the SAME location in the output canvas is blue too.
        # This proves the engine used the same exif-corrected geometry as
        # our independent reference, rather than assuming a fixed corner.
        expected_rgb = expected_upright.convert("RGB")
        marker_xy = None
        for y in range(0, exp_h, 4):
            for x in range(0, exp_w, 4):
                px = expected_rgb.getpixel((x, y))
                if px[2] > px[0]:
                    marker_xy = (x, y)
                    break
            if marker_xy is not None:
                break
        assert marker_xy is not None, "reference image has no marker pixel"

        mx, my = marker_xy
        actual_pixel = out_img.convert("RGB").getpixel((left + mx, top + my))
        assert actual_pixel[2] > actual_pixel[0]


class TestScaling:
    def test_downscale_when_source_at_or_above_preset(self) -> None:
        source = _solid_image(2000, 1500, (10, 20, 30))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=1080))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.final_width == 1080
        assert result.final_height == 1080

    def test_step_down_to_nearest_lower_preset(self) -> None:
        # 1000x1000 source with preset=1200 requested: source can't fill
        # 1200 without upscaling, so it must step down to 800, not stay 1200.
        source = _solid_image(1000, 1000, (10, 20, 30))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=1200))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.final_width == 800
        assert result.final_height == 800

    def test_sub_800_source_pasted_centered_unscaled(self) -> None:
        source = _solid_image(400, 300, (10, 20, 30))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=1080))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.final_width == 800
        assert result.final_height == 800

        out_img = Image.open(io.BytesIO(result.output_bytes)).convert("RGB")
        left = (800 - 400) // 2
        top = (800 - 300) // 2
        # Inside the pasted region: should be the source color (10, 20, 30) ish.
        inside = out_img.getpixel((left + 200, top + 150))
        assert abs(inside[0] - 10) <= 5
        assert abs(inside[1] - 20) <= 5
        assert abs(inside[2] - 30) <= 5
        # Outside the pasted region: should be the fill color (white).
        outside = out_img.getpixel((5, 5))
        assert outside[0] > 240 and outside[1] > 240 and outside[2] > 240

    def test_source_exactly_at_preset_boundary(self) -> None:
        source = _solid_image(1080, 1080, (5, 5, 5))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=1080))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.final_width == 1080
        assert result.final_height == 1080

    def test_source_one_pixel_under_preset_boundary(self) -> None:
        # 1079 is one under the 1080 preset: must NOT upscale to 1080,
        # must step down to the nearest lower preset (800).
        source = _solid_image(1079, 1079, (5, 5, 5))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=1080))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.final_width == 800
        assert result.final_height == 800


class TestTransparency:
    def test_transparent_png_flattened_onto_fill_color(self) -> None:
        source = Image.new("RGBA", (500, 500), (0, 255, 0, 0))  # fully transparent
        source_bytes = _encode(source, fmt="PNG")

        result = normalize_image(source_bytes, _default_params(preset=800, fill_color="#ffffff"))

        assert result.outcome == NormalizationOutcome.SUCCESS
        out_img = Image.open(io.BytesIO(result.output_bytes))
        assert out_img.mode != "RGBA"
        assert "A" not in out_img.getbands()
        rgb = out_img.convert("RGB")
        pixel = rgb.getpixel((400, 400))
        assert pixel[0] > 240 and pixel[1] > 240 and pixel[2] > 240


class TestOutputFormat:
    def test_output_is_jpeg_no_exif(self) -> None:
        source = _solid_image(900, 900, (100, 100, 100))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=800))

        assert result.outcome == NormalizationOutcome.SUCCESS
        out_img = Image.open(io.BytesIO(result.output_bytes))
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        exif = out_img.getexif()
        assert len(exif) == 0


class TestSizeLadder:
    def test_walks_quality_ladder_and_reports_too_large(self) -> None:
        # A big, high-entropy (noisy) image compresses poorly at any quality,
        # so with a tiny max_output_bytes budget every rung of the ladder
        # (85 -> 80 -> 75 -> 70) must fail and the outcome must be TOO_LARGE.
        import random

        random.seed(42)
        source = Image.new("RGB", (1200, 1200))
        pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)) for _ in range(1200 * 1200)]
        source.putdata(pixels)
        source_bytes = _encode(source)

        result = normalize_image(
            source_bytes,
            _default_params(preset=1200, max_output_bytes=100),
        )

        assert result.outcome == NormalizationOutcome.TOO_LARGE
        assert result.output_bytes is None

    def test_succeeds_within_budget_at_default_quality(self) -> None:
        source = _solid_image(800, 800, (50, 60, 70))
        source_bytes = _encode(source)

        result = normalize_image(source_bytes, _default_params(preset=800))

        assert result.outcome == NormalizationOutcome.SUCCESS
        assert result.quality_used == 85
        assert len(result.output_bytes) <= 3145728


class TestCorruptInput:
    def test_corrupt_input_returns_decode_failure_without_raising(self) -> None:
        garbage = b"not-an-image-at-all" * 20

        result = normalize_image(garbage, _default_params())

        assert result.outcome == NormalizationOutcome.DECODE_FAILED
        assert result.output_bytes is None
