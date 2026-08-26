"""Tests for tn_image_normalizer.params: normalization parameters and their fingerprint."""

import pytest

from app.services.tn_image_normalizer.params import PRESETS, NormalizationParams, params_fingerprint

DEFAULT_FINGERPRINT = "0bcda5f11b1fd30f5392167da5a19619"


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


class TestParamsFingerprint:
    def test_matches_documented_value_for_default_inputs(self) -> None:
        params = _default_params()
        assert params_fingerprint(params) == DEFAULT_FINGERPRINT

    def test_changing_preset_changes_fingerprint(self) -> None:
        default_fp = params_fingerprint(_default_params())
        changed_fp = params_fingerprint(_default_params(preset=1200))
        assert changed_fp != default_fp

    def test_changing_fill_color_changes_fingerprint(self) -> None:
        default_fp = params_fingerprint(_default_params())
        changed_fp = params_fingerprint(_default_params(fill_color="#000000"))
        assert changed_fp != default_fp

    def test_changing_quality_changes_fingerprint(self) -> None:
        default_fp = params_fingerprint(_default_params())
        changed_fp = params_fingerprint(_default_params(quality=90))
        assert changed_fp != default_fp

    def test_changing_max_output_bytes_changes_fingerprint(self) -> None:
        default_fp = params_fingerprint(_default_params())
        changed_fp = params_fingerprint(_default_params(max_output_bytes=1048576))
        assert changed_fp != default_fp

    def test_is_deterministic_across_calls(self) -> None:
        params = _default_params()
        first = params_fingerprint(params)
        second = params_fingerprint(_default_params())
        assert first == second

    def test_params_dataclass_is_frozen(self) -> None:
        params = _default_params()
        try:
            params.preset = 800  # type: ignore[misc]
        except Exception:
            pass
        else:
            raise AssertionError("NormalizationParams must be frozen")


class TestNormalizationParamsValidation:
    """`NormalizationParams` rejects values the engine cannot honor.

    The engine documents itself as a pure function that never raises: every
    outcome travels through `NormalizationResult.outcome`. That promise only
    holds when the parameters are known-good by the time the engine sees them,
    so the dataclass is the single validation gate.
    """

    def test_rejects_a_preset_outside_the_supported_set(self) -> None:
        with pytest.raises(ValueError, match="preset"):
            _default_params(preset=900)

    def test_accepts_every_supported_preset(self) -> None:
        for preset in PRESETS:
            assert _default_params(preset=preset).preset == preset

    def test_rejects_shorthand_hex_fill_color(self) -> None:
        # Valid in CSS, unparseable by the engine's byte-pair slicing.
        with pytest.raises(ValueError, match="fill_color"):
            _default_params(fill_color="#fff")

    def test_rejects_a_named_fill_color(self) -> None:
        with pytest.raises(ValueError, match="fill_color"):
            _default_params(fill_color="white")

    def test_rejects_a_fill_color_with_non_hex_digits(self) -> None:
        with pytest.raises(ValueError, match="fill_color"):
            _default_params(fill_color="#gggggg")

    def test_accepts_full_length_hex_regardless_of_case(self) -> None:
        assert _default_params(fill_color="#FFFFFF").fill_color == "#FFFFFF"

    def test_rejects_a_quality_outside_one_to_one_hundred(self) -> None:
        for quality in (0, 101, -1):
            with pytest.raises(ValueError, match="quality"):
                _default_params(quality=quality)

    def test_rejects_a_non_positive_max_output_bytes(self) -> None:
        with pytest.raises(ValueError, match="max_output_bytes"):
            _default_params(max_output_bytes=0)
