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

FAILURE POLICY
--------------
A batch run must survive one bad URL. Every network error, timeout, and
non-2xx response is converted into a `DownloadResult` in the
`download_failed` state — no exception ever escapes to the caller, so one
dead image can never abort the remaining items in the run.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx

from app.services.tn_image_normalizer.states import (
    ITEM_DOWNLOAD_FAILED,
    ITEM_DOWNLOADED,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


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


async def download_source_image(
    source_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> DownloadResult:
    """Download `source_url` and return its bytes plus their sha256 hex digest.

    Never raises: any transport error, timeout, non-2xx status, or empty
    body becomes a `download_failed` result.
    """
    url = (source_url or "").strip()
    if not url:
        return _failed(source_url, "empty source_url")

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the run
        return _failed(url, f"{type(exc).__name__}: {exc}")

    status_code = response.status_code
    if not 200 <= status_code < 300:
        return _failed(url, f"HTTP {status_code}")

    content = response.content or b""
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
