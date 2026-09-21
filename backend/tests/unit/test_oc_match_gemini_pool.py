"""Unit tests for Gemini pool: 429/503/fallback and malformed JSON (no live API)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock, call, patch

import pytest
from google.genai import errors as genai_errors

from app.core.config import Settings
from app.services.oc_match.gemini_pool import GeminiPool, load_keys, load_pool


def _quota_err() -> genai_errors.ClientError:
    return genai_errors.ClientError(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})


def _demanda_err() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"message": "UNAVAILABLE"}})


def _ok(payload: str = '{"ok": true}') -> MagicMock:
    good = MagicMock()
    good.text = payload
    return good


class TestGeminiPoolRotationAndJson:
    def test_429_rotates_to_second_key(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client_a = MagicMock()
            client_b = MagicMock()
            ClientCls.side_effect = [client_a, client_b]
            pool = GeminiPool(["key-a", "key-b"], "gemini-test")
            client_a.models.generate_content.side_effect = _quota_err()
            client_b.models.generate_content.return_value = _ok()
            result = pool.generate_json("hello")
        assert result == {"ok": True}
        assert pool.i == 1

    def test_malformed_json_raises_runtime_error(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client = MagicMock()
            ClientCls.return_value = client
            pool = GeminiPool(["key-a"], "gemini-test")
            bad = MagicMock()
            bad.text = "not-json {{"
            client.models.generate_content.return_value = bad
            with pytest.raises(RuntimeError, match="JSON malformado"):
                pool.generate_json("hello")


class TestGeminiPoolFallback429:
    def test_429_all_keys_switches_to_fallback(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            primary_a = MagicMock()
            primary_b = MagicMock()
            fallback_a = MagicMock()
            ClientCls.side_effect = [primary_a, primary_b, fallback_a]
            pool = GeminiPool(
                ["key-a", "key-b"],
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            )
            primary_a.models.generate_content.side_effect = _quota_err()
            primary_b.models.generate_content.side_effect = _quota_err()
            fallback_a.models.generate_content.return_value = _ok('{"ok": true}')
            with patch("app.services.oc_match.gemini_pool.time.sleep") as sleep:
                result = pool.generate_json("hello")
        assert result == {"ok": True}
        assert pool.en_fallback is True
        assert pool.model == "gemini-3.1-flash-lite"
        assert pool.i == 0
        sleep.assert_not_called()
        fallback_a.models.generate_content.assert_called()
        assert fallback_a.models.generate_content.call_args.kwargs["model"] == "gemini-3.1-flash-lite"

    def test_429_on_fallback_raises(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            primary = MagicMock()
            fallback = MagicMock()
            ClientCls.side_effect = [primary, fallback]
            pool = GeminiPool(["key-a"], "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
            primary.models.generate_content.side_effect = _quota_err()
            fallback.models.generate_content.side_effect = _quota_err()
            with pytest.raises(genai_errors.ClientError):
                pool.generate_json("hello")
        assert pool.en_fallback is True
        assert pool.model == "gemini-3.1-flash-lite"

    def test_429_disabled_fallback_raises(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client_a = MagicMock()
            client_b = MagicMock()
            ClientCls.side_effect = [client_a, client_b]
            pool = GeminiPool(["key-a", "key-b"], "gemini-3.5-flash-lite")
            client_a.models.generate_content.side_effect = _quota_err()
            client_b.models.generate_content.side_effect = _quota_err()
            with pytest.raises(genai_errors.ClientError):
                pool.generate_json("hello")
        assert pool.en_fallback is False
        assert pool.model == "gemini-3.5-flash-lite"


class TestGeminiPoolDemanda503:
    def test_503_sleeps_5_then_10_then_rotates(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client_a = MagicMock()
            client_b = MagicMock()
            ClientCls.side_effect = [client_a, client_b]
            pool = GeminiPool(["key-a", "key-b"], "gemini-test")
            client_a.models.generate_content.side_effect = _demanda_err()
            client_b.models.generate_content.return_value = _ok()
            with patch("app.services.oc_match.gemini_pool.time.sleep") as sleep:
                result = pool.generate_json("hello")
        assert result == {"ok": True}
        assert pool.i == 1
        sleep.assert_has_calls([call(5), call(10)])
        assert sleep.call_count == 2

    def test_503_all_keys_seen_switches_to_fallback(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            primary_a = MagicMock()
            primary_b = MagicMock()
            fallback_a = MagicMock()
            ClientCls.side_effect = [primary_a, primary_b, fallback_a]
            pool = GeminiPool(
                ["key-a", "key-b"],
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            )
            primary_a.models.generate_content.side_effect = _demanda_err()
            primary_b.models.generate_content.side_effect = _demanda_err()
            fallback_a.models.generate_content.return_value = _ok('{"via": "fallback"}')
            with patch("app.services.oc_match.gemini_pool.time.sleep") as sleep:
                result = pool.generate_json("hello")
        assert result == {"via": "fallback"}
        assert pool.en_fallback is True
        assert pool.model == "gemini-3.1-flash-lite"
        sleep.assert_has_calls([call(5), call(10)])
        assert sleep.call_count == 2


class TestGeminiPoolFallbackPersistAndLogs:
    def test_empty_or_same_fallback_disabled(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client"):
            none_pool = GeminiPool(["key-a"], "gemini-3.5-flash-lite", None)
            empty_pool = GeminiPool(["key-a"], "gemini-3.5-flash-lite", "")
            same_pool = GeminiPool(
                ["key-a"],
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash-lite",
            )
            ok_pool = GeminiPool(
                ["key-a"],
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            )
        assert none_pool.fallback_model is None
        assert empty_pool.fallback_model is None
        assert same_pool.fallback_model is None
        assert ok_pool.fallback_model == "gemini-3.1-flash-lite"
        assert none_pool.en_fallback is False

    def test_second_generate_json_stays_on_fallback(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            primary = MagicMock()
            fallback = MagicMock()
            ClientCls.side_effect = [primary, fallback]
            pool = GeminiPool(["key-a"], "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
            primary.models.generate_content.side_effect = _quota_err()
            fallback.models.generate_content.side_effect = [
                _ok('{"phase": "extract"}'),
                _ok('{"phase": "match"}'),
            ]
            first = pool.generate_json("extract")
            assert first == {"phase": "extract"}
            assert pool.en_fallback is True
            assert pool.model == "gemini-3.1-flash-lite"
            second = pool.generate_json("match")
        assert second == {"phase": "match"}
        assert pool.model == "gemini-3.1-flash-lite"
        assert pool.en_fallback is True
        models_used = [c.kwargs["model"] for c in fallback.models.generate_content.call_args_list]
        assert models_used == ["gemini-3.1-flash-lite", "gemini-3.1-flash-lite"]

    def test_logs_include_model_and_key_slot_omit_secrets(self, caplog: pytest.LogCaptureFixture) -> None:
        secret_a = "sk-SUPERSECRET-xyz"
        secret_b = "sk-OTHERSECRET-abc"
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client_a = MagicMock()
            client_b = MagicMock()
            ClientCls.side_effect = [client_a, client_b]
            pool = GeminiPool([secret_a, secret_b], "gemini-3.5-flash-lite")
            client_a.models.generate_content.side_effect = _quota_err()
            client_b.models.generate_content.return_value = _ok()
            with caplog.at_level(logging.INFO):
                pool.generate_json("hello")
        text = caplog.text
        assert "model=gemini-3.5-flash-lite" in text
        assert "key 2/2" in text
        assert secret_a not in text
        assert secret_b not in text

    def test_load_pool_logs_fallback_disabled_when_same(self, caplog: pytest.LogCaptureFixture) -> None:
        secret = "sk-LOADPOOL-SECRET"
        with (
            patch("app.services.oc_match.gemini_pool.genai.Client"),
            patch("app.services.oc_match.gemini_pool.settings") as settings_mock,
        ):
            settings_mock.GEMINI_API_KEY = secret
            settings_mock.GEMINI_API_KEY_2 = None
            settings_mock.GEMINI_API_KEY_3 = None
            settings_mock.GEMINI_MODEL = "gemini-3.5-flash-lite"
            settings_mock.GEMINI_MODEL_FALLBACK = "gemini-3.5-flash-lite"
            with caplog.at_level(logging.INFO):
                pool = load_pool()
        assert pool.fallback_model is None
        assert "fallback=disabled" in caplog.text
        assert "model=gemini-3.5-flash-lite" in caplog.text
        assert secret not in caplog.text

    def test_config_and_generate_json_defaults(self) -> None:
        assert Settings.model_fields["GEMINI_MODEL"].default == "gemini-3.5-flash-lite"
        assert Settings.model_fields["GEMINI_MODEL_FALLBACK"].default == "gemini-3.1-flash-lite"
        assert inspect.signature(GeminiPool.generate_json).parameters["attempts"].default == 12

    def test_load_keys_primary_default(self) -> None:
        with patch("app.services.oc_match.gemini_pool.settings") as settings_mock:
            settings_mock.GEMINI_API_KEY = "k"
            settings_mock.GEMINI_API_KEY_2 = None
            settings_mock.GEMINI_API_KEY_3 = None
            settings_mock.GEMINI_MODEL = ""
            keys, model = load_keys()
        assert keys == ["k"]
        assert model == "gemini-3.5-flash-lite"
