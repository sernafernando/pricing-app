"""ml-sync-pipeline T5 (S5): the freshness targets and the owner's message. No database."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.ml_publications import freshness


class TestTargets:
    def test_an_env_value_naming_some_resources_keeps_the_other_defaults(self) -> None:
        targets = Settings(ML_PUB_FRESHNESS_TARGET_SECONDS={"items": 60}).ML_PUB_FRESHNESS_TARGET_SECONDS

        assert targets["items"] == 60
        assert targets["prices"] == 300

    @pytest.mark.parametrize("bad", [{"stock": 60}, {"items": 0}, {"items": "2m"}])
    def test_an_unknown_resource_or_a_bad_value_is_refused(self, bad) -> None:
        with pytest.raises(ValidationError):
            Settings(ML_PUB_FRESHNESS_TARGET_SECONDS=bad)


class TestTheMessage:
    def test_families_are_counted_as_families(self) -> None:
        report = {
            "resources": {
                "items": {"late": 2, "oldest_late_seconds": 400, "target_seconds": 120},
                "family": {"late": 1, "oldest_late_seconds": 90000, "target_seconds": 86400},
            }
        }

        message = freshness.late_message(report)

        assert "estado de la publicación: 2 publicaciones" in message
        assert "familia: 1 familia," in message

    # Owner, 2026-11-03: "pero me dice más atrasada 2 min y el objetivo es 2 min". A delay just past its target
    # was rounded down to the target itself.
    @pytest.mark.parametrize(
        ("late", "target", "shown"),
        [
            (125, 120, "la más atrasada 3 min (objetivo 2 min)"),
            (301, 300, "la más atrasada 6 min (objetivo 5 min)"),
            (25.2 * 3600, 25 * 3600, "la más atrasada 26 h (objetivo 25 h)"),
            (44 * 3600, 25 * 3600, "la más atrasada 44 h (objetivo 25 h)"),
        ],
    )
    def test_the_delay_is_rounded_up_so_it_never_reads_as_the_target(self, late, target, shown) -> None:
        report = {"resources": {"items": {"late": 1, "oldest_late_seconds": late, "target_seconds": target}}}

        assert shown in freshness.late_message(report)
