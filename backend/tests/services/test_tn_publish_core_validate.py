"""Unit tests for the D3 measurement gate (PC6, MP4 co-shipping proof)."""

from app.services.tn_publish_core.resolve import Resolved
from app.services.tn_publish_core.validate import validate_measurements


def _fields(**overrides):
    base = {
        "weight": Resolved(1.0, "gbp"),
        "width": Resolved(13.0, "gbp"),
        "depth": Resolved(2.0, "gbp"),
        "height": Resolved(8.0, "gbp"),
    }
    base.update(overrides)
    return base


class TestMeasurementGateBlocksOnMissingDimension:
    def test_publish_blocked_when_weight_resolves_empty(self):
        result = validate_measurements(_fields(weight=Resolved(None, "empty")))

        assert result.blocked is True
        assert any("weight" in reason for reason in result.blocked_reasons)

    def test_publish_blocked_names_every_missing_measurement_not_just_the_first(self):
        result = validate_measurements(_fields(weight=Resolved(None, "empty"), height=Resolved(None, "empty")))

        assert result.blocked is True
        assert len(result.blocked_reasons) == 2
        joined = " ".join(result.blocked_reasons)
        assert "weight" in joined
        assert "height" in joined

    def test_complete_fields_are_never_blocked(self):
        result = validate_measurements(_fields())

        assert result.blocked is False
        assert result.blocked_reasons == []


class TestProfileFillsGapAndUnblocks:
    """MP4 — the same item unblocks the moment a profile supplies all four
    fields (proving the gate and the profile fallback ship as one working
    unit, not two independently-shippable halves)."""

    def test_item_with_no_gbp_measurements_unblocks_once_a_profile_fills_all_four(self):
        blocked = validate_measurements(
            {
                "weight": Resolved(None, "empty"),
                "width": Resolved(None, "empty"),
                "depth": Resolved(None, "empty"),
                "height": Resolved(None, "empty"),
            }
        )
        assert blocked.blocked is True

        unblocked = validate_measurements(
            {
                "weight": Resolved(1.5, "profile"),
                "width": Resolved(30.0, "profile"),
                "depth": Resolved(20.0, "profile"),
                "height": Resolved(20.0, "profile"),
            }
        )
        assert unblocked.blocked is False
        assert unblocked.blocked_reasons == []
