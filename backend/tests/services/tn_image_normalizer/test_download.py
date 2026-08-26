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
import pytest
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tn_image_normalizer.download import (
    DownloadResult,
    _PinnedAddressTransport,
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


class TestPinnedAddressTransport:
    """The connection must go to the address we validated, not to a fresh one.

    Validating with `getaddrinfo` and then letting httpx resolve again is a
    TOCTOU window: a short-TTL attacker answers our check with a public
    address and httpx's with an internal one.
    """

    def _capture(self, transport, request):
        captured = {}

        async def fake_send(_self, sent):
            captured["request"] = sent
            return httpx.Response(200, content=IMAGE_BYTES)

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            asyncio.run(transport.handle_async_request(request))
        return captured["request"]

    def test_connect_target_is_the_validated_ip(self) -> None:
        transport = _PinnedAddressTransport()
        transport.pin("example.com", PUBLIC_IP)

        sent = self._capture(transport, httpx.Request("GET", "https://example.com/a.jpg"))

        assert sent.url.host == PUBLIC_IP
        assert sent.url.path == "/a.jpg"

    def test_original_host_header_is_preserved(self) -> None:
        transport = _PinnedAddressTransport()
        transport.pin("example.com", PUBLIC_IP)

        sent = self._capture(transport, httpx.Request("GET", "https://example.com/a.jpg"))

        assert sent.headers["host"] == "example.com"

    def test_tls_is_verified_against_the_hostname_not_the_ip(self) -> None:
        # Pinning the IP into the URL would otherwise make the handshake
        # check the certificate against "93.184.216.34" and fail every real
        # HTTPS host — the tempting "fix" being to disable verification.
        transport = _PinnedAddressTransport()
        transport.pin("example.com", PUBLIC_IP)

        sent = self._capture(transport, httpx.Request("GET", "https://example.com/a.jpg"))

        assert sent.extensions["sni_hostname"] == "example.com"

    def test_idn_host_is_pinned_and_matches_the_punycoded_lookup(self) -> None:
        # httpx punycodes the request URL host, so a pin stored under the raw
        # unicode host would never be found: the request would go out UNPINNED
        # with a fresh DNS lookup, silently reopening the rebinding window.
        transport = _PinnedAddressTransport()
        transport.pin("m\u00fcnchen.example", PUBLIC_IP)

        sent = self._capture(transport, httpx.Request("GET", "https://m\u00fcnchen.example/a.jpg"))

        assert sent.url.host == PUBLIC_IP
        assert sent.headers["host"] == "xn--mnchen-3ya.example"

    def test_punycoded_idn_host_is_pinned_and_matches_the_decoded_lookup(self) -> None:
        # The mirror case, and the one that actually bites: `urlsplit` keeps
        # the punycode a GBP row carries, while httpx decodes it back to
        # unicode. The pin key and the lookup key must be normalized the same
        # way or the request goes out UNPINNED with a fresh DNS lookup.
        transport = _PinnedAddressTransport()
        transport.pin("xn--mnchen-3ya.example", PUBLIC_IP)

        sent = self._capture(transport, httpx.Request("GET", "https://xn--mnchen-3ya.example/a.jpg"))

        assert sent.url.host == PUBLIC_IP

    def test_unpinned_host_is_refused_instead_of_being_sent(self) -> None:
        # Fail CLOSED: `_validate_target` is the only thing that decides what
        # may be requested, so a host arriving here without a pin is a bug,
        # and letting it through would be an unvalidated request.
        transport = _PinnedAddressTransport()
        reached = []

        async def fake_send(_self, sent):
            reached.append(sent)
            return httpx.Response(200, content=IMAGE_BYTES)

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            with pytest.raises(Exception):
                asyncio.run(transport.handle_async_request(httpx.Request("GET", "https://example.com/a.jpg")))

        assert reached == [], "an unpinned request reached the network"

    def test_unpinned_request_ends_as_download_failed(self) -> None:
        reached = []

        async def fake_send(_self, sent):
            reached.append(sent)
            return httpx.Response(200, content=IMAGE_BYTES)

        with patch.object(_PinnedAddressTransport, "pin", lambda self, host, address: None):
            with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
                with patch(
                    "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                    side_effect=lambda *a, **k: _addrinfo(PUBLIC_IP),
                ):
                    result = asyncio.run(download_source_image("https://example.com/a.jpg"))

        assert result.state == ITEM_DOWNLOAD_FAILED
        assert reached == [], "an unpinned request reached the network"


class TestDnsRebindingIsClosed:
    def test_second_resolution_cannot_reach_an_internal_target(self) -> None:
        # The attacker's host answers our validation with a public address
        # and would answer httpx's connect-time lookup with 127.0.0.1.
        targets: list[str] = []

        async def fake_send(_self, sent):
            targets.append(sent.url.host)
            return httpx.Response(200, content=IMAGE_BYTES)

        resolutions = [_addrinfo(PUBLIC_IP), _addrinfo("127.0.0.1")]

        def rebinding_getaddrinfo(*args, **kwargs):
            return resolutions.pop(0) if resolutions else _addrinfo("127.0.0.1")

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            with patch(
                "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                side_effect=rebinding_getaddrinfo,
            ):
                result = asyncio.run(download_source_image("https://rebind.example/a.jpg"))

        assert result.state == ITEM_DOWNLOADED
        assert targets == [PUBLIC_IP], f"connected to an unvalidated target: {targets}"

    def test_each_redirect_hop_is_pinned_to_its_own_validated_address(self) -> None:
        targets: list[str] = []
        second_ip = "93.184.216.35"

        async def fake_send(_self, sent):
            targets.append(sent.url.host)
            if len(targets) == 1:
                return httpx.Response(302, headers={"location": "https://second.example/b.jpg"})
            return httpx.Response(200, content=IMAGE_BYTES)

        resolutions = [_addrinfo(PUBLIC_IP), _addrinfo(second_ip)]

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            with patch(
                "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                side_effect=lambda *a, **k: resolutions.pop(0),
            ):
                result = asyncio.run(download_source_image("https://first.example/a.jpg"))

        assert result.state == ITEM_DOWNLOADED
        assert targets == [PUBLIC_IP, second_ip]


class TestConnectionsAreNeverSharedBetweenHostnames:
    """Pinning must not let two hostnames share one TLS connection.

    httpcore keys its pool on `request.url.origin`, i.e. `(scheme, host,
    port)`, and `sni_hostname` is read only when a connection is OPENED
    (`httpcore/_async/connection.py`), never as part of that key. Once the
    URL host is rewritten to the pinned address, the key becomes the IP —
    so `https://first.example` and `https://second.example` behind one CDN
    address collapse onto a single pool entry, and the second hostname
    would reuse a connection whose certificate was verified for the first.
    A redirect between two hostnames of the same CDN is the common case.
    """

    def _two_hop_download(self, first_ip: str, second_ip: str):
        """Follow first.example -> second.example, recording each hop."""
        hops: list[dict] = []

        async def fake_send(_self, sent):
            hops.append(
                {
                    "transport": id(_self),
                    "sni": sent.extensions.get("sni_hostname"),
                    "host_header": sent.headers.get("host"),
                    "target": sent.url.host,
                }
            )
            if len(hops) == 1:
                return httpx.Response(302, headers={"location": "https://second.example/b.jpg"})
            return httpx.Response(200, content=IMAGE_BYTES)

        resolutions = {"first.example": first_ip, "second.example": second_ip}

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            with patch(
                "app.services.tn_image_normalizer.download.socket.getaddrinfo",
                side_effect=lambda host, *a, **kw: _addrinfo(resolutions[host]),
            ):
                result = asyncio.run(download_source_image("https://first.example/a.jpg"))
        return result, hops

    def test_two_hostnames_on_one_ip_do_not_share_a_connection_pool(self) -> None:
        result, hops = self._two_hop_download(PUBLIC_IP, PUBLIC_IP)

        assert result.state == ITEM_DOWNLOADED
        assert [hop["target"] for hop in hops] == [PUBLIC_IP, PUBLIC_IP]
        assert hops[0]["transport"] != hops[1]["transport"], (
            "both hostnames went through one connection pool keyed on the shared IP, "
            "so the second hostname could reuse a connection verified for the first"
        )

    def test_each_hostname_is_verified_under_its_own_name(self) -> None:
        _, hops = self._two_hop_download(PUBLIC_IP, PUBLIC_IP)

        assert [hop["sni"] for hop in hops] == ["first.example", "second.example"]
        assert [hop["host_header"] for hop in hops] == ["first.example", "second.example"]

    def test_pool_isolation_also_holds_when_the_ips_differ(self) -> None:
        _, hops = self._two_hop_download(PUBLIC_IP, "93.184.216.35")

        assert hops[0]["transport"] != hops[1]["transport"]


class TestHostHeaderNeverCarriesCredentials:
    """A `Host` header is `<host>[:<port>]` — never userinfo.

    Credentials in a `Host` header are both an invalid header value and a
    secret written into a place that gets logged by every intermediary.
    """

    def _sent(self, url: str, pin_host: str):
        transport = _PinnedAddressTransport()
        transport.pin(pin_host, PUBLIC_IP)
        captured = {}

        async def fake_send(_self, sent):
            captured["request"] = sent
            return httpx.Response(200, content=IMAGE_BYTES)

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", fake_send):
            asyncio.run(transport.handle_async_request(httpx.Request("GET", url)))
        return captured["request"]

    def test_userinfo_is_not_copied_into_the_host_header(self) -> None:
        sent = self._sent("https://user:pass@cdn.example/a.jpg", "cdn.example")

        assert sent.headers["host"] == "cdn.example"
        assert "pass" not in sent.headers["host"]
        assert "@" not in sent.headers["host"]

    def test_non_default_port_is_kept_in_the_host_header(self) -> None:
        sent = self._sent("https://cdn.example:8443/a.jpg", "cdn.example")

        assert sent.headers["host"] == "cdn.example:8443"

    def test_default_port_is_omitted_from_the_host_header(self) -> None:
        sent = self._sent("https://cdn.example:443/a.jpg", "cdn.example")

        assert sent.headers["host"] == "cdn.example"
