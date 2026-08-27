"""Tienda Nube image normalizer — download stage (slice 5).

Fetches the raw bytes of one source image and hashes them. Nothing else:
no decoding, no resizing, no disk, no database.

SESSION BOUNDARY
----------------
This module never accepts, holds, or imports a SQLAlchemy `Session`. A
download is the slowest step in the pipeline (a remote host, a timeout
budget, a retry), and a session held across it is a pooled connection
parked on network latency — exactly the shape that exhausted the pool
before. The stage therefore takes plain data in and returns plain data
out; persisting the result is the caller's job, in its own short
transaction. `test_download.py` asserts this structurally.

UNTRUSTED INPUT
---------------
`source_url` comes from the GBP report, i.e. from outside our trust
boundary, and this code runs on a server that can reach the internal
network. Two guards therefore apply to every hop:

* Only `http` and `https` are fetched. Anything else (`file:`, `ftp:`,
  `gopher:`, a bare hostname) fails closed.
* The host is resolved with `socket.getaddrinfo` and every answer must be
  a public address. Loopback, RFC1918, link-local (including the
  `169.254.169.254` cloud metadata endpoint), reserved, multicast and
  unspecified addresses are refused. Checking the URL string alone would
  miss a hostname that simply *points* at an internal address, so the
  resolved addresses are what is judged.

The connection is then PINNED to the exact address that was judged.
`_PinnedAddressTransport` rewrites the request URL's host to that address
while sending the original `Host` header and, for HTTPS, the original
hostname as `sni_hostname` — so the TLS handshake and the certificate check
still run against the hostname, never against the IP literal. Because that
rewrite makes httpcore's pool key the IP rather than the hostname, the
transport keeps ONE POOL PER PINNED HOSTNAME, so two hostnames behind one
CDN address can never share a connection whose certificate was verified for
only one of them. A host that somehow reaches the transport without a pin
is refused outright: this stage fails closed, never open.

Resolving once and letting httpx resolve again at connect time would leave
a DNS rebinding window: a short-TTL attacker answers our check with a
public address and httpx's with an internal one. Pinning means there is no
second resolution to poison. Every redirect hop is validated and pinned the
same way.

Redirects are followed by hand (`follow_redirects=False`) precisely so
that each `Location` is validated before it is requested: letting httpx
follow them would hand an attacker a single redirect straight past the
guard.

SIZE CEILING
------------
The body is streamed and capped at `max_bytes`. `TN_IMG_MAX_OUTPUT_BYTES`
is deliberately *not* reused as the default: it bounds the normalized
JPEG we produce, whereas this limit bounds the raw camera-original we
accept, which is legitimately several times larger. `Content-Length` is
honoured when present but never trusted on its own — a lying or absent
header is still caught by the running total, so a 500 MB body can never
be materialized in a worker's memory.

FAILURE POLICY
--------------
A batch run must survive one bad URL. Every rejected scheme, blocked
target, network error, timeout, non-2xx response, oversized body and
empty body is converted into a `DownloadResult` in the `download_failed`
state — no exception ever escapes to the caller, so one dead image can
never abort the remaining items in the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from functools import partial
from urllib.parse import urlsplit

import httpx

from app.services.tn_image_normalizer.states import (
    ITEM_DOWNLOAD_FAILED,
    ITEM_DOWNLOADED,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0

# 25 MiB: comfortably above any real product photo a supplier publishes,
# far below what would threaten a worker holding several of them at once.
# Not `settings.TN_IMG_MAX_OUTPUT_BYTES` — that is the ceiling of the
# normalized output, not of the raw input we are willing to read.
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
# Keyed by the schemes in ALLOWED_SCHEMES; the assert keeps the two from
# drifting apart, since a scheme allowed but unmapped would KeyError here.
DEFAULT_PORTS = {"http": 80, "https": 443}
assert set(DEFAULT_PORTS) == set(ALLOWED_SCHEMES)


@dataclass(frozen=True)
class DownloadResult:
    """Plain-data outcome of one source image fetch.

    `content` and `source_hash` are both populated on success and both
    `None` on failure — there is no half-downloaded state, so a caller
    can branch on `state` alone.
    """

    source_url: str
    state: str
    source_hash: str | None = None
    content: bytes | None = None
    error: str | None = None


def _failed(source_url: str, error: str) -> DownloadResult:
    logger.warning("tn_image_normalizer.download failed (url=%s): %s", source_url, error)
    return DownloadResult(source_url=source_url, state=ITEM_DOWNLOAD_FAILED, error=error)


def _is_public_address(raw_address: str) -> bool:
    """True only for an address we are willing to open a connection to."""
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError:
        return False
    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


class UnpinnedHostError(RuntimeError):
    """A request reached the transport for a host that was never pinned."""


def _pin_key(host: str) -> str:
    """Normalize `host` the way httpx normalizes a URL host.

    `urlsplit` hands back the hostname exactly as the GBP row spelled it,
    while httpx round-trips IDN through IDNA — a punycoded `xn--...` host is
    decoded back to unicode, and a unicode one may be encoded. Keying the
    pins on the raw string therefore stores `xn--mnchen-3ya.example` and
    looks up `münchen.example`, misses, and (before the fail-closed guard
    below) sent the request out unpinned with a fresh DNS lookup: silently
    the exact rebinding window this transport exists to close. Both sides go
    through httpx's own normalization so they cannot disagree.
    """
    try:
        return (httpx.URL(f"//{host}").host or host).lower()
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return host.lower()


class _PinnedAddressTransport(httpx.AsyncBaseTransport):
    """Connects to the address that was validated, not to a fresh lookup.

    The URL host is replaced by the pinned IP so no second DNS resolution
    can happen, while the original hostname keeps travelling in the `Host`
    header and in the `sni_hostname` extension. httpcore passes that
    extension to the TLS handshake as `server_hostname`, so SNI and
    certificate verification still target the hostname: pinning the address
    costs nothing in TLS strength.

    ONE POOL PER HOSTNAME
    ---------------------
    The rewrite has a sharp edge that a single pool would turn into a hole.
    httpcore decides whether an idle connection may serve a request with
    `connection.can_handle_request(request.url.origin)`, and `Origin` is
    exactly `(scheme, host, port)` — `sni_hostname` is read only inside
    `_connect`, when a connection is OPENED, and is not part of that key.
    Once the host is the pinned IP, the key is the IP, so two hostnames
    behind one CDN address share one pool entry: `https://first.example`
    redirecting to `https://second.example` would reuse a connection whose
    certificate was verified for `first.example`, and `second.example`'s
    certificate would never be checked at all. Redirects between hostnames
    of the same CDN are the ordinary case, not an exotic one.

    Each pinned hostname therefore gets its own `AsyncHTTPTransport`, i.e.
    its own connection pool. Isolation then does not depend on the pool key
    at all: a connection opened for one hostname is not reachable from
    another, whatever address either resolved to. Keep-alive survives
    WITHIN a hostname, which is where it is worth anything — dropping it
    globally instead would also cost nothing measurable today (each
    `download_source_image` call builds its own client, so nothing is
    reused across images anyway) but would silently become the wrong
    default the day a batch reuses one client across a catalog.

    A host with no pin is REFUSED, not passed through. `_validate_target` is
    the only thing that decides what may be requested, and it pins every
    target it approves — so an unpinned host arriving here is a bug, and
    letting it through would be an unvalidated, freshly resolved request.
    `download_source_image` turns the exception into a `download_failed`
    result like any other transport error.
    """

    def __init__(self, **kwargs) -> None:
        self._transport_kwargs = kwargs
        self._pins: dict[str, str] = {}
        self._transports: dict[str, httpx.AsyncHTTPTransport] = {}

    def pin(self, host: str, address: str) -> None:
        self._pins[_pin_key(host)] = address

    def _transport_for(self, host: str) -> httpx.AsyncHTTPTransport:
        transport = self._transports.get(host)
        if transport is None:
            transport = httpx.AsyncHTTPTransport(**self._transport_kwargs)
            self._transports[host] = transport
        return transport

    def _host_header(self, url: httpx.URL) -> str:
        """`<host>[:<port>]`, IDNA-encoded and without any userinfo.

        `URL.netloc` is httpx's own answer to this question: it is documented
        as "either `<host>` or `<host>:<port>`", lowercased and IDNA encoded,
        with the default port for the scheme already dropped and userinfo
        kept out (it lives in a separate component of the URI reference).
        Rebuilding it from `url.host` by hand would instead undo the IDNA
        encoding, since `url.host` decodes punycode back to unicode.
        """
        return url.netloc.decode("ascii")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = _pin_key(request.url.host or "")
        address = self._pins.get(host)
        if address is None:
            raise UnpinnedHostError(f"refusing to request unpinned host {host or '(none)'}")
        request.headers["host"] = self._host_header(request.url)
        request.extensions = {**request.extensions, "sni_hostname": request.url.host}
        request.url = request.url.copy_with(host=address)
        return await self._transport_for(host).handle_async_request(request)

    async def aclose(self) -> None:
        for transport in self._transports.values():
            await transport.aclose()
        self._transports.clear()


async def _validate_target(url: str) -> tuple[str | None, str | None]:
    """Validate `url`, returning `(error, address_to_pin)`.

    Exactly one half is ever populated: an error string when the URL must
    not be requested, otherwise the validated address the connection has to
    be pinned to.
    """
    # urlsplit itself, and `.port` in particular, raise on a garbled URL
    # (out-of-range port, unclosed IPv6 bracket). This guard runs BEFORE the
    # request's try block, so an escape here would abort the whole batch over
    # one bad row in the GBP report.
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        return f"malformed URL: {exc}", None

    if scheme not in ALLOWED_SCHEMES:
        return f"disallowed URL scheme: {scheme or '(none)'}", None

    if not host:
        return "URL has no host", None

    port = port or DEFAULT_PORTS[scheme]
    loop = asyncio.get_running_loop()
    try:
        answers = await loop.run_in_executor(
            None,
            partial(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM),
        )
    except Exception as exc:  # noqa: BLE001 - resolution failure is just a failed download
        return f"could not resolve host {host}: {type(exc).__name__}: {exc}", None

    addresses = [answer[4][0] for answer in answers]
    if not addresses:
        return f"host {host} resolved to no address", None
    for address in addresses:
        # One non-public answer is enough: the pin below picks one of these,
        # and a host that answers with any internal address is not a host we
        # are willing to talk to at all.
        if not _is_public_address(address):
            return f"blocked non-public address for host {host}: {address}", None
    return None, addresses[0]


def _declared_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes | None:
    """Accumulate the body, returning None as soon as it exceeds `max_bytes`."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def download_source_image(
    source_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> DownloadResult:
    """Download `source_url` and return its bytes plus their sha256 hex digest.

    Only `http`/`https` URLs resolving to public addresses are fetched, and
    every redirect hop is re-validated before it is requested (at most
    `MAX_REDIRECTS` hops). The body is streamed and refused once it passes
    `max_bytes`.

    Never raises: a rejected scheme, a blocked target, any transport error,
    timeout, non-2xx status, oversized body or empty body becomes a
    `download_failed` result.
    """
    url = (source_url or "").strip()
    if not url:
        return _failed(source_url, "empty source_url")

    target_error, address = await _validate_target(url)
    if target_error is not None:
        return _failed(url, target_error)

    transport = _PinnedAddressTransport()
    transport.pin(urlsplit(url).hostname or "", address or "")

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as response:
                    status_code = response.status_code

                    if status_code in REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            return _failed(url, f"HTTP {status_code} redirect without Location")
                        next_url = str(httpx.URL(current).join(location))
                        # Validate BEFORE requesting: an unchecked hop is the
                        # whole point of following redirects by hand.
                        hop_error, hop_address = await _validate_target(next_url)
                        if hop_error is not None:
                            return _failed(url, f"blocked redirect: {hop_error}")
                        # Pin this hop too: an unpinned hop reopens exactly
                        # the rebinding window the first one closes.
                        transport.pin(urlsplit(next_url).hostname or "", hop_address or "")
                        current = next_url
                        continue

                    if not 200 <= status_code < 300:
                        return _failed(url, f"HTTP {status_code}")

                    declared = _declared_length(response)
                    if declared is not None and declared > max_bytes:
                        return _failed(
                            url,
                            f"declared size {declared} exceeds max size {max_bytes} bytes",
                        )

                    content = await _read_capped(response, max_bytes)
                    if content is None:
                        return _failed(url, f"response body exceeds max size {max_bytes} bytes")
                    break
            else:
                return _failed(url, f"too many redirects (max {MAX_REDIRECTS})")
    except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the run
        return _failed(url, f"{type(exc).__name__}: {exc}")

    if not content:
        # A zero-byte body would otherwise hash to the sha256 of nothing and
        # dedup every empty download onto one bogus shared artifact.
        return _failed(url, "empty response body")

    return DownloadResult(
        source_url=url,
        state=ITEM_DOWNLOADED,
        source_hash=hashlib.sha256(content).hexdigest(),
        content=content,
    )
