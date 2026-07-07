"""
Unit tests — services/ml_questions/answer_shaping.py
(sdd/ml-questions-ai/answer-shaping follow-up)

Covers:
- get_answer_max_chars(): fail-safe int parsing (absent/malformed/non-positive
  -> default 300).
- resolve_closing_text(): global closing, absent/blank = off.
- resolve_signature(): default signature only for non-official-store items;
  per-store map for official-store items, including missing-entry / ""-entry
  / malformed-JSON fail-safe cases.
- assemble_final_answer(): assembly order + hard 2000-char ceiling.
"""

from __future__ import annotations

import logging

import pytest

from app.models.ml_bot_config import MlBotConfig
from app.services.ml_questions.answer_shaping import (
    _ANSWER_MAX_CHARS_CEILING,
    _DEFAULT_ANSWER_MAX_CHARS,
    _ML_HARD_CHAR_LIMIT,
    assemble_final_answer,
    get_answer_max_chars,
    resolve_closing_text,
    resolve_signature,
)

_LOGGER_NAME = "app.services.ml_questions.answer_shaping"


def _seed_config(db, clave: str, valor: str, tipo: str = "string") -> None:
    db.add(MlBotConfig(clave=clave, valor=valor, tipo=tipo))
    db.commit()


@pytest.fixture(autouse=True)
def _allow_log_propagation():
    """The `app` root logger sets propagate=False (app/core/logging.py) to
    avoid duplicate logs under uvicorn; re-enable propagation for the
    duration of these tests so caplog (which attaches to the root logger)
    can observe warnings emitted by `answer_shaping.logger`."""
    app_logger = logging.getLogger("app")
    original = app_logger.propagate
    app_logger.propagate = True
    try:
        yield
    finally:
        app_logger.propagate = original


class TestGetAnswerMaxChars:
    def test_defaults_when_absent(self, db) -> None:
        assert get_answer_max_chars(db) == _DEFAULT_ANSWER_MAX_CHARS

    def test_reads_configured_value(self, db) -> None:
        _seed_config(db, "answer_max_chars", "150")
        assert get_answer_max_chars(db) == 150

    def test_defaults_when_malformed(self, db) -> None:
        _seed_config(db, "answer_max_chars", "not-a-number")
        assert get_answer_max_chars(db) == _DEFAULT_ANSWER_MAX_CHARS

    def test_defaults_when_non_positive(self, db) -> None:
        _seed_config(db, "answer_max_chars", "0")
        assert get_answer_max_chars(db) == _DEFAULT_ANSWER_MAX_CHARS

    def test_defaults_when_empty_string(self, db) -> None:
        _seed_config(db, "answer_max_chars", "")
        assert get_answer_max_chars(db) == _DEFAULT_ANSWER_MAX_CHARS

    def test_clamps_above_ceiling(self, db, caplog) -> None:
        _seed_config(db, "answer_max_chars", "1990")
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert get_answer_max_chars(db) == _ANSWER_MAX_CHARS_CEILING
        assert "exceeds ceiling" in caplog.text

    def test_value_at_ceiling_unchanged(self, db) -> None:
        _seed_config(db, "answer_max_chars", "1500")
        assert get_answer_max_chars(db) == _ANSWER_MAX_CHARS_CEILING


class TestResolveClosingText:
    def test_off_when_absent(self, db) -> None:
        assert resolve_closing_text(db) == ""

    def test_off_when_blank(self, db) -> None:
        _seed_config(db, "answer_closing_text", "")
        assert resolve_closing_text(db) == ""

    def test_returns_configured_text(self, db) -> None:
        _seed_config(db, "answer_closing_text", "¡Saludos!")
        assert resolve_closing_text(db) == "¡Saludos!"


class TestResolveSignature:
    def test_default_signature_for_non_official_store(self, db) -> None:
        _seed_config(db, "answer_company_signature", "Somos Gauss Online")
        assert resolve_signature(db, None) == "Somos Gauss Online"

    def test_no_default_signature_when_unset(self, db) -> None:
        assert resolve_signature(db, None) == ""

    def test_official_store_ignores_default_signature(self, db) -> None:
        _seed_config(db, "answer_company_signature", "Somos Gauss Online")
        # No answer_signatures_by_store configured -> no entry for 2645.
        assert resolve_signature(db, 2645) == ""

    def test_official_store_with_map_entry(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", '{"2645": "Somos la tienda oficial TP-Link"}')
        assert resolve_signature(db, 2645) == "Somos la tienda oficial TP-Link"

    def test_official_store_missing_map_entry_is_failsafe_empty(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", '{"57997": "Somos Gauss Online"}')
        assert resolve_signature(db, 2645) == ""

    def test_official_store_explicit_empty_entry_means_no_signature(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", '{"2645": ""}')
        assert resolve_signature(db, 2645) == ""

    def test_malformed_json_means_no_per_store_signatures(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", "{not valid json")
        assert resolve_signature(db, 2645) == ""

    def test_non_object_json_means_no_per_store_signatures(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", "[1, 2, 3]")
        assert resolve_signature(db, 2645) == ""

    def test_non_string_map_value_means_no_signature(self, db) -> None:
        _seed_config(db, "answer_signatures_by_store", '{"2645": 123}')
        assert resolve_signature(db, 2645) == ""


class TestAssembleFinalAnswer:
    def test_answer_only_when_no_extras(self) -> None:
        assert assemble_final_answer("Hola, sí hay stock.", "", "") == "Hola, sí hay stock."

    def test_appends_closing_only(self) -> None:
        result = assemble_final_answer("Hola.", "¡Saludos!", "")
        assert result == "Hola.\n\n¡Saludos!"

    def test_appends_signature_only(self) -> None:
        result = assemble_final_answer("Hola.", "", "Somos Gauss Online")
        assert result == "Hola.\nSomos Gauss Online"

    def test_appends_closing_and_signature_in_order(self) -> None:
        result = assemble_final_answer("Hola.", "¡Saludos!", "Somos Gauss Online")
        assert result == "Hola.\n\n¡Saludos!\nSomos Gauss Online"

    def test_closing_dropped_whole_when_it_does_not_fit(self, caplog) -> None:
        answer = "a" * 1900
        closing = "b" * 500
        signature = "c" * 500
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = assemble_final_answer(answer, closing, signature)
        # Neither closing nor signature fit -> answer ships intact, no fragment.
        assert result == answer
        assert len(result) <= _ML_HARD_CHAR_LIMIT
        assert "dropped closing" in caplog.text

    def test_signature_dropped_whole_when_only_it_does_not_fit(self, caplog) -> None:
        answer = "a" * 1900
        closing = "b" * 50
        signature = "c" * 500
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = assemble_final_answer(answer, closing, signature)
        # Closing fits and stays intact; signature is dropped whole.
        assert result == f"{answer}\n\n{closing}"
        assert len(result) <= _ML_HARD_CHAR_LIMIT
        assert "dropped signature" in caplog.text

    def test_result_is_never_a_mid_component_fragment(self) -> None:
        answer = "a" * 1900
        closing = "b" * 500
        signature = "c" * 500
        result = assemble_final_answer(answer, closing, signature)
        valid_assemblies = {
            answer,
            f"{answer}\n\n{closing}",
            f"{answer}\n{signature}",
            f"{answer}\n\n{closing}\n{signature}",
        }
        assert result in valid_assemblies

    def test_short_text_untouched_by_cap(self) -> None:
        result = assemble_final_answer("short", "closing", "sig")
        assert len(result) < _ML_HARD_CHAR_LIMIT
