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
