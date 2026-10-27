"""WhatsApp messages to the owner through wabot.

wabot sends a message without `to` to the users' group, so `send_to_owner` never posts without the owner's
recipient (`WABOT_OWNER_TO`). A failure is returned, never raised: an alert must not break the job that sends it.
"""

from __future__ import annotations

import httpx

from app.core.config import settings

TIMEOUT_SECONDS = 8.0


def send_to_owner(message: str) -> str:
    """Send `message` to the owner. Returns "sent", "not_configured" or "failed: <reason>"."""
    if not settings.WABOT_TOKEN or not settings.WABOT_OWNER_TO:
        return "not_configured"
    try:
        response = httpx.post(
            f"{settings.WABOT_URL.rstrip('/')}/send",
            json={"message": message, "to": settings.WABOT_OWNER_TO},
            headers={"Authorization": f"Bearer {settings.WABOT_TOKEN}"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return f"failed: {type(exc).__name__}"
    if response.status_code >= 300:
        return f"failed: http {response.status_code}"
    return "sent"
