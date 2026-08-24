"""Async client for the Vikunja API (sdd/tickets-sync-vikunja, PR 1).

PR 1 scope: client only — nothing calls this yet (no hook, no loop, no
endpoint; that's PR 2/3). Adapted from a sync httpx script verified
end-to-end against the live instance (migrated 43 tickets with
attachments, labels, comments, kanban placement); this version is async
(`httpx.AsyncClient`, one client per call) because the callers are
`async def` hooks running on the app's asyncio loop — a sync client would
block the event loop.

Error taxonomy mirrors `app.services.ml_api_client`:
    - `VikunjaPermanentError`: 4xx except 429/408 — do not retry.
    - `VikunjaTransientError`: 429/408/5xx/timeout/connect — bounded retry.

Classification is by STATUS CODE ONLY, never by response body: Vikunja runs
on SQLite (single-writer), so "database is locked" arrives as a bare 500
with nothing in the body to parse.

The token is never logged, and error messages built from a response never
include headers (only status code + truncated body).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class VikunjaPermanentError(Exception):
    """A 4xx (except 429/408) rejection from Vikunja — the request is
    malformed/unauthorized/rejected. Do not retry."""

    def __init__(self, method: str, path: str, status_code: int, body: str) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {path} -> HTTP {status_code}: {body[:300]}")


class VikunjaTransientError(Exception):
    """A retryable failure: 429, 408, any 5xx, timeout, or connect error."""

    def __init__(self, method: str, path: str, status_code: Optional[int], detail: str) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        self.detail = detail
        status_repr = status_code if status_code is not None else "network error"
        super().__init__(f"{method} {path} -> {status_repr}: {detail[:300]}")


def _is_transient_status(status_code: int) -> bool:
    return status_code == 429 or status_code == 408 or status_code >= 500


class VikunjaClient:
    """Thin async wrapper over the Vikunja REST API (`/api/v1`)."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._api = base_url.rstrip("/") + "/api/v1"
        self._token = token
        self._timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        idempotent: bool = True,
        _max_attempts: int = 5,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue one request with the retry ladder: up to `_max_attempts`
        tries, 0.4s doubling backoff. Never retries 4xx other than 429/408.

        `idempotent=False` marks a call that CREATES something (`create_task`,
        attachment upload). Those must not be blindly retried: a timeout or a
        5xx can mean Vikunja committed the write and only the acknowledgement
        was lost, so retrying would create a second task. Retrying five times
        could create five. That failure is invisible to the ledger's
        `UNIQUE(ticket_id)`, which prevents a duplicate ROW, not a duplicate
        TASK — and it would defeat the ambiguity resolution downstream, which
        assumes a lost acknowledgement surfaces exactly once.

        429 and 408 stay retryable even for writes: both mean the server
        rejected the request WITHOUT processing it (rate limited / never
        received a complete request), so no write can have happened.
        """
        wait = 0.4
        last_exc: Optional[Exception] = None

        for attempt in range(_max_attempts):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(method, f"{self._api}{path}", headers=self._headers(), **kwargs)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                # The ambiguous case: the request may have been applied and we
                # simply never saw the answer. Surface it instead of guessing.
                if not idempotent:
                    logger.warning(
                        "vikunja: %s %s failed ambiguously (%s); not retried because it is a write",
                        method,
                        path,
                        type(exc).__name__,
                    )
                    raise VikunjaTransientError(method, path, None, str(exc)) from exc
                if attempt < _max_attempts - 1:
                    await asyncio.sleep(wait)
                    wait *= 2
                    continue
                raise VikunjaTransientError(method, path, None, str(exc)) from exc

            unprocessed = response.status_code in (429, 408)
            if unprocessed or (_is_transient_status(response.status_code) and idempotent):
                if attempt < _max_attempts - 1:
                    await asyncio.sleep(wait)
                    wait *= 2
                    continue
                logger.warning(
                    "vikunja: %s %s exhausted %d attempts (HTTP %s)", method, path, _max_attempts, response.status_code
                )
                raise VikunjaTransientError(method, path, response.status_code, response.text or "(empty body)")

            if _is_transient_status(response.status_code):
                # A 5xx on a write: same ambiguity as a timeout.
                logger.warning(
                    "vikunja: %s %s returned HTTP %s; not retried because it is a write",
                    method,
                    path,
                    response.status_code,
                )
                raise VikunjaTransientError(method, path, response.status_code, response.text or "(empty body)")

            if response.status_code >= 400:
                raise VikunjaPermanentError(method, path, response.status_code, response.text)

            return response

        # Unreachable in practice (the loop always returns or raises), but
        # keeps mypy/type-checkers honest and avoids a silent None return.
        raise VikunjaTransientError(method, path, None, str(last_exc) if last_exc else "exhausted retries")

    # -- tasks ---------------------------------------------------------

    async def create_task(
        self,
        *,
        project_id: int,
        title: str,
        description: Optional[str] = None,
        done: bool = False,
        hex_color: Optional[str] = None,
        _max_attempts: int = 5,
    ) -> Dict[str, Any]:
        """Create a task in `project_id`. Returns the parsed Vikunja task."""
        payload: Dict[str, Any] = {"title": title, "done": done}
        if description is not None:
            payload["description"] = description
        if hex_color is not None:
            payload["hex_color"] = hex_color

        # `idempotent=False`: this PUT CREATES a task. Every call makes a new
        # one, so a blind retry after a lost acknowledgement duplicates it.
        response = await self._request(
            "PUT",
            f"/projects/{project_id}/tasks",
            json=payload,
            idempotent=False,
            _max_attempts=_max_attempts,
        )
        return response.json()

    async def list_tasks(
        self,
        *,
        project_id: int,
        _max_attempts: int = 5,
    ) -> List[Dict[str, Any]]:
        """List every task in `project_id`, following Vikunja's
        `x-pagination-total-pages` response header. A naive single-page
        implementation silently drops tasks past page 1."""
        results: List[Dict[str, Any]] = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            response = await self._request(
                "GET",
                f"/projects/{project_id}/tasks",
                params={"page": page},
                _max_attempts=_max_attempts,
            )
            results.extend(response.json())
            total_pages = int(response.headers.get("x-pagination-total-pages", "1"))
            page += 1

        return results

    # -- attachments -----------------------------------------------------

    async def upload_attachment(
        self,
        *,
        task_id: int,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
        _max_attempts: int = 5,
    ) -> Dict[str, Any]:
        """Upload `content` as a new attachment on `task_id`. Every call
        creates a NEW attachment record (sdd/tickets-sync-vikunja PR 2) —
        `idempotent=False` for the exact same reason as `create_task`: a
        lost acknowledgement on retry would attach the file twice."""
        files = {"files": (filename, content, content_type or "application/octet-stream")}
        response = await self._request(
            "PUT",
            f"/tasks/{task_id}/attachments",
            files=files,
            idempotent=False,
            _max_attempts=_max_attempts,
        )
        return response.json()

    async def list_attachments(
        self,
        *,
        task_id: int,
        _max_attempts: int = 5,
    ) -> List[Dict[str, Any]]:
        """Attachments already on `task_id`. This is what makes draining
        idempotent WITHOUT a local watermark: `upload_attachment` creates a
        new record on every call, so the drain has to know what Vikunja
        already holds rather than infer it from a timestamp."""
        response = await self._request("GET", f"/tasks/{task_id}/attachments", _max_attempts=_max_attempts)
        return response.json() or []
