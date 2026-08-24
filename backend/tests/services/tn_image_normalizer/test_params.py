"""Tests for tn_image_normalizer.params: normalization parameters and their fingerprint."""

from app.services.tn_image_normalizer.params import NormalizationParams, params_fingerprint

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
