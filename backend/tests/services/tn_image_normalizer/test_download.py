"""Tests for tn_image_normalizer.download: source image fetch stage.

Coroutines are driven with `asyncio.run`: the project has NO pytest-asyncio
configured, so `@pytest.mark.asyncio` would be silently skipped and the test
would pass without ever running.

`source_url` values come from the GBP report, i.e. from outside our trust
boundary, so the SSRF and size-ceiling guards are exercised here as first
class behaviour, not as an afterthought.
"""

import asyncio
import hashlib
import inspect
import socket

import httpx
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tn_image_normalizer.download import (
    DownloadResult,
    download_source_image,
)
from app.services.tn_image_normalizer.states import ITEM_DOWNLOAD_FAILED, ITEM_DOWNLOADED

IMAGE_BYTES = b"\xff\xd8\xff\xe0not-a-real-jpeg-but-stable-bytes"
PUBLIC_IP = "93.184.216.34"


class _StreamResponse:
    """Minimal stand-in for the object `httpx.AsyncClient.stream` yields."""

    def __init__(self, status_code: int, headers=None, chunks=()) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self._chunks = list(chunks)

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _StreamContext:
    def __init__(self, response: _StreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _StreamResponse:
        return self._response

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeClient:
    def __init__(self, responses, side_effect=None) -> None:
        self._responses = list(responses)
        self._side_effect = side_effect
        self.requested_urls: list[str] = []
        self.follow_redirects = None

    def stream(self, method: str, url: str, **kwargs):
        self.requested_urls.append(url)
        if self._side_effect is not None:
            raise self._side_effect
        return _StreamContext(self._responses.pop(0))


def _client_mock(*, responses=None, side_effect=None):
    """Patch `httpx.AsyncClient` with a fake whose `stream` is scripted."""
    client = _FakeClient(responses or [], side_effect=side_effect)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    def factory(*args, **kwargs):
        client.follow_redirects = kwargs.get("follow_redirects")
        factory.kwargs = kwargs
        return ctx

    factory_mock = MagicMock(side_effect=factory)
    factory_mock.client = client
    return factory_mock


def _ok(chunks=(IMAGE_BYTES,), headers=None) -> _StreamResponse:
    return _StreamResponse(200, headers=headers, chunks=chunks)


def _addrinfo(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def _run(url: str, factory, resolved=(PUBLIC_IP,), **kwargs) -> DownloadResult:
    with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
        with patch(
            "app.services.tn_image_normalizer.download.socket.getaddrinfo",
            return_value=_addrinfo(*resolved),
        ):
            return asyncio.run(download_source_image(url, **kwargs))


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
        result = _run("https://x/a.jpg", _client_mock(responses=[_ok()]))

        assert isinstance(result, DownloadResult)
        assert result.state == ITEM_DOWNLOADED
        assert result.content == IMAGE_BYTES
        assert result.error is None

    def test_source_hash_is_sha256_of_raw_bytes(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_ok()]))

        assert result.source_hash == hashlib.sha256(IMAGE_BYTES).hexdigest()

    def test_chunks_are_concatenated_in_order(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_ok(chunks=(b"ab", b"cd", b"ef"))]))

        assert result.content == b"abcdef"

    def test_empty_body_is_a_failure_not_a_hash_of_nothing(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_ok(chunks=())]))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert result.source_hash is None


class TestFailures:
    def test_http_500_maps_to_download_failed(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_StreamResponse(500, chunks=(b"boom",))]))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert result.content is None
        assert result.source_hash is None
        assert "500" in (result.error or "")

    def test_http_404_maps_to_download_failed(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_StreamResponse(404)]))

        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_network_exception_never_escapes_to_the_caller(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(side_effect=httpx.ConnectError("no route to host")))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "no route to host" in (result.error or "")

    def test_timeout_maps_to_download_failed(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(side_effect=httpx.ReadTimeout("timed out")))

        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_blank_url_fails_without_any_network_call(self) -> None:
        factory = _client_mock(responses=[_ok()])
        result = _run("   ", factory)

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()

    def test_resolution_failure_maps_to_download_failed(self) -> None:
        factory = _client_mock(responses=[_ok()])
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            with patch(
                "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                side_effect=socket.gaierror("name does not resolve"),
            ):
                result = asyncio.run(download_source_image("https://nope.invalid/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()


class TestSchemeAllowlist:
    def test_file_scheme_is_rejected_without_any_network_call(self) -> None:
        factory = _client_mock(responses=[_ok()])
        result = _run("file:///etc/passwd", factory)

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()

    def test_ftp_scheme_is_rejected(self) -> None:
        result = _run("ftp://example.com/a.jpg", _client_mock(responses=[_ok()]))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_gopher_scheme_is_rejected(self) -> None:
        result = _run("gopher://example.com/a.jpg", _client_mock(responses=[_ok()]))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_schemeless_url_is_rejected(self) -> None:
        result = _run("example.com/a.jpg", _client_mock(responses=[_ok()]))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_http_and_https_are_allowed(self) -> None:
        result = _run("http://example.com/a.jpg", _client_mock(responses=[_ok()]))
        assert result.state == ITEM_DOWNLOADED


class TestSsrfTargetGuard:
    def test_loopback_literal_is_blocked(self) -> None:
        factory = _client_mock(responses=[_ok()])
        result = _run("http://127.0.0.1/a.jpg", factory, resolved=("127.0.0.1",))

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()

    def test_cloud_metadata_endpoint_is_blocked(self) -> None:
        result = _run(
            "http://169.254.169.254/latest/meta-data/",
            _client_mock(responses=[_ok()]),
            resolved=("169.254.169.254",),
        )
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_rfc1918_private_address_is_blocked(self) -> None:
        result = _run("http://10.0.0.5/a.jpg", _client_mock(responses=[_ok()]), resolved=("10.0.0.5",))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_hostname_resolving_to_a_private_address_is_blocked(self) -> None:
        factory = _client_mock(responses=[_ok()])
        result = _run("https://evil.example.com/a.jpg", factory, resolved=("192.168.1.10",))

        assert result.state == ITEM_DOWNLOAD_FAILED
        factory.assert_not_called()

    def test_ipv6_loopback_is_blocked(self) -> None:
        result = _run("https://evil.example.com/a.jpg", _client_mock(responses=[_ok()]), resolved=("::1",))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_any_non_public_answer_blocks_even_if_another_is_public(self) -> None:
        result = _run(
            "https://evil.example.com/a.jpg",
            _client_mock(responses=[_ok()]),
            resolved=(PUBLIC_IP, "127.0.0.1"),
        )
        assert result.state == ITEM_DOWNLOAD_FAILED


class TestRedirectHandling:
    def test_client_does_not_follow_redirects_itself(self) -> None:
        factory = _client_mock(responses=[_ok()])
        _run("https://x/a.jpg", factory)

        assert factory.client.follow_redirects is False

    def test_redirect_to_a_public_host_is_followed(self) -> None:
        factory = _client_mock(
            responses=[
                _StreamResponse(302, headers={"location": "https://cdn.example.com/b.jpg"}),
                _ok(),
            ]
        )
        result = _run("https://x/a.jpg", factory)

        assert result.state == ITEM_DOWNLOADED
        assert factory.client.requested_urls == [
            "https://x/a.jpg",
            "https://cdn.example.com/b.jpg",
        ]

    def test_redirect_to_the_metadata_endpoint_is_blocked(self) -> None:
        factory = _client_mock(
            responses=[
                _StreamResponse(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}),
                _ok(),
            ]
        )
        with patch("app.services.tn_image_normalizer.download.httpx.AsyncClient", factory):
            with patch(
                "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                side_effect=lambda host, *a, **kw: _addrinfo(
                    "169.254.169.254" if host == "169.254.169.254" else PUBLIC_IP
                ),
            ):
                result = asyncio.run(download_source_image("https://x/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        # The blocked hop was never requested.
        assert factory.client.requested_urls == ["https://x/a.jpg"]

    def test_redirect_to_a_disallowed_scheme_is_blocked(self) -> None:
        factory = _client_mock(responses=[_StreamResponse(301, headers={"location": "file:///etc/passwd"})])
        result = _run("https://x/a.jpg", factory)

        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_relative_redirect_is_resolved_against_the_current_url(self) -> None:
        factory = _client_mock(
            responses=[
                _StreamResponse(302, headers={"location": "/b.jpg"}),
                _ok(),
            ]
        )
        result = _run("https://x/a.jpg", factory)

        assert result.state == ITEM_DOWNLOADED
        assert factory.client.requested_urls[-1] == "https://x/b.jpg"

    def test_redirect_without_location_is_a_failure(self) -> None:
        result = _run("https://x/a.jpg", _client_mock(responses=[_StreamResponse(302)]))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_redirect_chain_is_capped(self) -> None:
        hops = [_StreamResponse(302, headers={"location": f"https://x/{i}.jpg"}) for i in range(20)]
        factory = _client_mock(responses=hops)
        result = _run("https://x/a.jpg", factory)

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "redirect" in (result.error or "").lower()
        assert len(factory.client.requested_urls) <= 6


class TestSizeCeiling:
    def test_content_length_over_the_limit_fails_without_reading_the_body(self) -> None:
        body_read = {"n": 0}

        class _Counting(_StreamResponse):
            async def aiter_bytes(self):
                body_read["n"] += 1
                yield b"x" * 100

        response = _Counting(200, headers={"content-length": "999999999"}, chunks=())
        result = _run("https://x/a.jpg", _client_mock(responses=[response]), max_bytes=1024)

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "size" in (result.error or "").lower()
        assert body_read["n"] == 0

    def test_lying_content_length_is_caught_while_streaming(self) -> None:
        response = _StreamResponse(
            200,
            headers={"content-length": "10"},
            chunks=(b"x" * 600, b"x" * 600),
        )
        result = _run("https://x/a.jpg", _client_mock(responses=[response]), max_bytes=1024)

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "size" in (result.error or "").lower()
        assert result.content is None

    def test_missing_content_length_over_the_limit_is_caught_while_streaming(self) -> None:
        response = _StreamResponse(200, chunks=(b"x" * 2048,))
        result = _run("https://x/a.jpg", _client_mock(responses=[response]), max_bytes=1024)

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert "size" in (result.error or "").lower()

    def test_body_exactly_at_the_limit_is_accepted(self) -> None:
        response = _StreamResponse(200, chunks=(b"x" * 1024,))
        result = _run("https://x/a.jpg", _client_mock(responses=[response]), max_bytes=1024)

        assert result.state == ITEM_DOWNLOADED
        assert result.content == b"x" * 1024

    def test_unparsable_content_length_does_not_raise(self) -> None:
        response = _StreamResponse(200, headers={"content-length": "not-a-number"}, chunks=(IMAGE_BYTES,))
        result = _run("https://x/a.jpg", _client_mock(responses=[response]), max_bytes=1024)

        assert result.state == ITEM_DOWNLOADED


class TestMalformedUrlNeverRaises:
    """A malformed URL is a failed download, not an exception.

    `urlsplit(...).port` raises for an out-of-range port, and the target
    guard runs BEFORE the try block that converts errors into results — so
    one garbled row in the GBP report would abort the whole batch.
    """

    def test_out_of_range_port_fails_without_raising(self) -> None:
        result = asyncio.run(download_source_image("http://example.com:99999/a.jpg"))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_unclosed_ipv6_bracket_fails_without_raising(self) -> None:
        result = asyncio.run(download_source_image("http://[::1/a.jpg"))
        assert result.state == ITEM_DOWNLOAD_FAILED

    def test_negative_port_fails_without_raising(self) -> None:
        result = asyncio.run(download_source_image("http://example.com:-1/a.jpg"))
        assert result.state == ITEM_DOWNLOAD_FAILED
