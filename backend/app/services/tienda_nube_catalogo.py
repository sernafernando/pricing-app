"""Fetches the whole Tienda Nube catalog (`GET /v1/{store}/products`, paged) for the worker handler `tienda_nube.sync`.

Same pagination and partial-fetch rule as the old cron script: an error after some pages returns what was fetched
with `completo=False`, so the sync updates those products and inactivates nothing. Every request is bounded by the
time left before `deadline`; running out of it also ends the fetch as partial.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PER_PAGE = 200
REQUEST_TIMEOUT_SECONDS = 20.0
# Under this much time left a new page is not worth asking for.
MIN_REQUEST_SECONDS = 3.0


def _segundos_restantes(deadline: datetime) -> float:
    return (deadline - datetime.now(UTC)).total_seconds()


def fetch_productos(*, deadline: datetime) -> tuple[list[dict], bool]:
    """Returns `(products, completo)`. Raises `RuntimeError` when the TN credentials are not configured."""
    store_id, token = settings.TN_STORE_ID, settings.TN_ACCESS_TOKEN
    if not store_id or not token:
        raise RuntimeError("TN_STORE_ID / TN_ACCESS_TOKEN no configurados")
    url = f"https://api.tiendanube.com/v1/{store_id}/products"
    headers = {"Authentication": f"bearer {token}", "User-Agent": "GAUSS Pricing App (worker)"}
    products: list[dict] = []
    page = 1
    with httpx.Client() as client:
        while True:
            remaining = _segundos_restantes(deadline)
            if remaining < MIN_REQUEST_SECONDS:
                logger.warning(
                    "tienda_nube.sync: deadline reached after %s pages (%s products), partial fetch: "
                    "nothing is inactivated and the next interval retries",
                    page - 1,
                    len(products),
                )
                return products, False
            try:
                response = client.get(
                    url,
                    headers=headers,
                    params={"page": page, "per_page": PER_PAGE},
                    timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("tienda_nube.sync: page %s failed, partial fetch: %s", page, exc)
                return products, False
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                return products, isinstance(batch, list)
            products.extend(batch)
            if len(batch) < PER_PAGE:
                return products, True
            page += 1
