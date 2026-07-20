"""Shared bridge between async client methods and synchronous callers.

Used by both `ml_promotions_write_service.py` and
`app/scripts/drain_promo_refresh.py` to call `MLWebhookClient`'s async
methods from synchronous code paths.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any


def resolve_maybe_async(value: Any) -> Any:
    """Bridges an async client's methods into a synchronous caller.

    Real calls return a coroutine (awaited here via `asyncio.run`);
    unit-test mocks (`patch.object(..., return_value=...)`) return the
    plain value directly, so both paths work unchanged.
    """
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value
