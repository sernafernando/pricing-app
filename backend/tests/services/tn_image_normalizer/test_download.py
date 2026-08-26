"""Tests for tn_image_normalizer.download: source image fetch stage.

Coroutines are driven with `asyncio.run`: the project has NO pytest-asyncio
configured, so `@pytest.mark.asyncio` would be silently skipped and the test
would pass without ever running.
"""

import asyncio
import hashlib
import inspect

import httpx
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tn_image_normalizer.download import (
    DownloadResult,
    download_source_image,
)
from app.services.tn_image_normalizer.states import ITEM_DOWNLOAD_FAILED, ITEM_DOWNLOADED

IMAGE_BYTES = b"\xff\xd8\xff\xe0not-a-real-jpeg-but-stable-bytes"


def _client_mock(*, response=None, side_effect=None) -> MagicMock:
    """Build a patched `httpx.AsyncClient` whose `get` is controlled."""
    client = MagicMock()
    client.get = AsyncMock(return_value=response, side_effect=side_effect)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory


def _response(status_code: int, content: bytes = b"") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    return response


class TestSessionBoundary:
    """The download stage may never hold a SQLAlchemy Session."""

    def test_download_signature_declares_no_session_parameter(self) -> None:
        signature = inspect.signature(download_source_image)
        for param in signature.parameters.values():
            assert param.annotation is not Session
            assert "Session" not in str(param.annotation)

    def test_download_return_annotation_is_plain_data(self) -> None:
        signature = inspect.signature(download_source_image)
        assert "Session" not in str(signature.return_annotation)


class TestHappyPath:
    def test_returns_downloaded_state_with_bytes(self) -> None:
        factory = _client_mock(response=_response(200, IMAGE_BYTES))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert isinstance(result, DownloadResult)
        assert result.state == ITEM_DOWNLOADED
        assert result.content == IMAGE_BYTES
        assert result.error is None

    def test_source_hash_is_sha256_of_raw_bytes(self) -> None:
        factory = _client_mock(response=_response(200, IMAGE_BYTES))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.source_hash == hashlib.sha256(IMAGE_BYTES).hexdigest()

    def test_empty_body_is_a_failure_not_a_hash_of_nothing(self) -> None:
        factory = _client_mock(response=_response(200, b""))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert result.source_hash is None


class TestFailures:
    def test_http_500_maps_to_download_failed(self) -> None:
        factory = _client_mock(response=_response(500, b"boom"))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert result.content is None
        assert result.source_hash is None
        assert "500" in (result.error or "")

    def test_http_404_maps_to_download_failed(self) -> None:
        factory = _client_mock(response=_response(404))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_network_exception_never_escapes_to_the_caller(self) -> None:
        factory = _client_mock(side_effect=httpx.ConnectError("no route to host"))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "no route to host" in (result.error or "")

    def test_timeout_maps_to_download_failed(self) -> None:
        factory = _client_mock(side_effect=httpx.ReadTimeout("timed out"))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_blank_url_fails_without_any_network_call(self) -> None:
        factory = _client_mock(response=_response(200, IMAGE_BYTES))
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            result = asyncio.run(download_source_image("   "))

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()
