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
        _max_attempts: int = 5,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue one request with the retry ladder: 429 + any 5xx, up to
        `_max_attempts` tries, 0.4s doubling backoff between attempts.
        Never retries 4xx other than 429/408."""
        wait = 0.4
        last_exc: Optional[Exception] = None

        for attempt in range(_max_attempts):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(method, f"{self._api}{path}", headers=self._headers(), **kwargs)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < _max_attempts - 1:
                    await asyncio.sleep(wait)
                    wait *= 2
                    continue
                raise VikunjaTransientError(method, path, None, str(exc)) from exc

            if _is_transient_status(response.status_code):
                if attempt < _max_attempts - 1:
                    await asyncio.sleep(wait)
                    wait *= 2
                    continue
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

        response = await self._request(
            "PUT",
            f"/projects/{project_id}/tasks",
            json=payload,
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
