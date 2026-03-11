"""
SSE stream endpoint — single multiplexed connection per client.

Clients subscribe to channels via query params and receive real-time
notification events when backend mutations occur. Events are lightweight
signals ("something changed"); the client re-fetches data via REST.

Usage:
    GET /api/sse/stream?channels=etiquetas:changed,notificaciones:updated
    Authorization: Bearer <token>
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.core.sse import SSEConnectionManager
from app.models.usuario import Usuario

logger = get_logger(__name__)

router = APIRouter(prefix="/sse", tags=["SSE"])

# ── Valid channel registry ───────────────────────────────────────

VALID_CHANNELS = {
    "etiquetas:changed",
    "notificaciones:updated",
    "free-shipping:count",
    "alertas:updated",
}


@router.get("/stream")
async def sse_stream(
    request: Request,
    channels: str = Query(
        ...,
        description="Comma-separated channel names to subscribe to",
        examples=["etiquetas:changed,alertas:updated"],
    ),
    current_user: Usuario = Depends(get_current_user),
) -> StreamingResponse:
    """
    Server-Sent Events stream endpoint.

    Opens a long-lived connection that pushes events when subscribed
    channels have updates. Client should reconnect on disconnect.

    Requires authentication via Authorization header.
    """
    # Parse and validate channels
    requested_channels = [ch.strip() for ch in channels.split(",") if ch.strip()]
    if not requested_channels:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one channel is required",
        )

    valid = [ch for ch in requested_channels if ch in VALID_CHANNELS]
    invalid = [ch for ch in requested_channels if ch not in VALID_CHANNELS]

    if invalid:
        logger.warning(
            "SSE: client requested invalid channels: %s (user=%s)",
            invalid,
            current_user.username,
        )

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No valid channels. Valid: {', '.join(sorted(VALID_CHANNELS))}",
        )

    manager: SSEConnectionManager | None = request.app.state.sse_manager
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSE not available (Redis not connected)",
        )
    client_id, queue = manager.register(valid)

    logger.info(
        "SSE: client %s connected (user=%s, channels=%s, total=%d)",
        client_id,
        current_user.username,
        valid,
        manager.active_connections,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Yields SSE events from the client's queue, with heartbeat."""
        heartbeat_seconds = request.app.state.sse_heartbeat_seconds
        try:
            # Initial connection comment
            yield ": connected\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                    if event is None:
                        break  # Sentinel: connection evicted or server shutting down
                    yield event
                except asyncio.TimeoutError:
                    # No events for heartbeat_seconds → send heartbeat
                    yield ": heartbeat\n\n"
        finally:
            manager.unregister(client_id)
            logger.info(
                "SSE: client %s disconnected (total=%d)",
                client_id,
                manager.active_connections,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
