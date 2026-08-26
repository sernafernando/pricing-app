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
* KNOWN GAP — DNS rebinding: we resolve the host, then httpx resolves it
  AGAIN when it connects. A short-TTL attacker can answer our check with a
  public address and httpx's with an internal one. Closing this needs a
  custom transport that connects to the IP we validated while sending the
  original Host header; until then the guard stops static internal targets
  and redirect chains, NOT an actively rebinding host.
* The host is resolved with `socket.getaddrinfo` and every answer must be
  a public address. Loopback, RFC1918, link-local (including the
  `169.254.169.254` cloud metadata endpoint), reserved, multicast and
  unspecified addresses are refused. Checking the URL string alone would
  miss a hostname that simply *points* at an internal address, so the
  resolved addresses are what is judged.

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
DEFAULT_PORTS = {"http": 80, "https": 443}


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


async def _validate_target(url: str) -> str | None:
    """Return an error string when `url` must not be requested, else None."""
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
        return f"malformed URL: {exc}"

    if scheme not in ALLOWED_SCHEMES:
        return f"disallowed URL scheme: {scheme or '(none)'}"

    if not host:
        return "URL has no host"

    port = port or DEFAULT_PORTS[scheme]
    loop = asyncio.get_running_loop()
    try:
        answers = await loop.run_in_executor(
            None,
            partial(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM),
        )
    except Exception as exc:  # noqa: BLE001 - resolution failure is just a failed download
        return f"could not resolve host {host}: {type(exc).__name__}: {exc}"

    addresses = [answer[4][0] for answer in answers]
    if not addresses:
        return f"host {host} resolved to no address"
    for address in addresses:
        # One non-public answer is enough: httpx may pick exactly that one.
        if not _is_public_address(address):
            return f"blocked non-public address for host {host}: {address}"
    return None


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

    target_error = await _validate_target(url)
    if target_error is not None:
        return _failed(url, target_error)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
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
                        hop_error = await _validate_target(next_url)
                        if hop_error is not None:
                            return _failed(url, f"blocked redirect: {hop_error}")
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
