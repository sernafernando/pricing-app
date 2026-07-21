"""
T-6: Unit tests — services/ml_questions/policy.py fail-safe config accessors
for the dynamic few-shot flywheel (sdd/ml-bot-dynamic-fewshot, design "Config
keys" table).

Covers: `is_fewshot_capture_enabled`, `is_fewshot_dynamic_enabled`,
`get_fewshot_k`, `get_fewshot_similarity_threshold` — all fail-safe (malformed
or absent config never raises, always falls back to the documented default),
both enable flags default `False` (dark launch).
"""

from __future__ import annotations

import pytest

from app.models.ml_bot_config import MlBotConfig
from app.services.ml_questions import policy


def _seed(db, clave: str, valor: str, tipo: str = "string") -> None:
    db.add(MlBotConfig(clave=clave, valor=valor, tipo=tipo))
    db.flush()


class TestFewshotCaptureEnabled:
    def test_defaults_false_when_absent(self, db) -> None:
        assert policy.is_fewshot_capture_enabled(db) is False

    def test_true_when_configured(self, db) -> None:
        _seed(db, "fewshot_capture_enabled", "true", "bool")
        assert policy.is_fewshot_capture_enabled(db) is True

    def test_false_when_configured_false(self, db) -> None:
        _seed(db, "fewshot_capture_enabled", "false", "bool")
        assert policy.is_fewshot_capture_enabled(db) is False

    def test_defaults_false_when_empty_string(self, db) -> None:
        _seed(db, "fewshot_capture_enabled", "", "bool")
        assert policy.is_fewshot_capture_enabled(db) is False


class TestFewshotDynamicEnabled:
    def test_defaults_false_when_absent(self, db) -> None:
        assert policy.is_fewshot_dynamic_enabled(db) is False

    def test_true_when_configured(self, db) -> None:
        _seed(db, "fewshot_dynamic_enabled", "true", "bool")
        assert policy.is_fewshot_dynamic_enabled(db) is True


class TestGetFewshotK:
    def test_default_when_absent(self, db) -> None:
        assert policy.get_fewshot_k(db) == 5

    def test_configured_value(self, db) -> None:
        _seed(db, "fewshot_k", "8", "int")
        assert policy.get_fewshot_k(db) == 8

    def test_malformed_falls_back_to_default(self, db) -> None:
        _seed(db, "fewshot_k", "not-a-number", "int")
        assert policy.get_fewshot_k(db) == 5

    def test_clamped_to_ceiling(self, db) -> None:
        _seed(db, "fewshot_k", "999", "int")
        assert policy.get_fewshot_k(db) == 20

    def test_clamped_to_floor(self, db) -> None:
        _seed(db, "fewshot_k", "0", "int")
        assert policy.get_fewshot_k(db) == 1

    def test_clamped_to_floor_when_negative(self, db) -> None:
        _seed(db, "fewshot_k", "-5", "int")
        assert policy.get_fewshot_k(db) == 1


class TestGetFewshotSimilarityThreshold:
    def test_default_when_absent(self, db) -> None:
        assert policy.get_fewshot_similarity_threshold(db) == 0.0

    def test_configured_value(self, db) -> None:
        _seed(db, "fewshot_similarity_threshold", "0.75", "string")
        assert policy.get_fewshot_similarity_threshold(db) == pytest.approx(0.75)

    def test_malformed_falls_back_to_default(self, db) -> None:
        _seed(db, "fewshot_similarity_threshold", "not-a-float", "string")
        assert policy.get_fewshot_similarity_threshold(db) == 0.0

    def test_clamped_to_ceiling(self, db) -> None:
        _seed(db, "fewshot_similarity_threshold", "5.0", "string")
        assert policy.get_fewshot_similarity_threshold(db) == 1.0

    def test_clamped_to_floor_when_negative(self, db) -> None:
        _seed(db, "fewshot_similarity_threshold", "-1.0", "string")
        assert policy.get_fewshot_similarity_threshold(db) == 0.0
