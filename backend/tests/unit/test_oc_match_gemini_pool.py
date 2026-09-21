"""Unit tests for Gemini pool: 429 rotation and malformed JSON (no live API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from app.services.oc_match.gemini_pool import GeminiPool


class TestGeminiPoolRotationAndJson:
    def test_429_rotates_to_second_key(self) -> None:
        with patch("app.services.oc_match.gemini_pool.genai.Client") as ClientCls:
            client_a = MagicMock()
            client_b = MagicMock()
            ClientCls.side_effect = [client_a, client_b]
            pool = GeminiPool(["key-a", "key-b"], "gemini-test")
            client_a.models.generate_content.side_effect = genai_errors.ClientError(
                429, {"error": {"message": "RESOURCE_EXHAUSTED"}}
            )
            good = MagicMock()
            good.text = '{"ok": true}'
            client_b.models.generate_content.return_value = good
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
