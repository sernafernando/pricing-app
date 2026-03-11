"""
SSE (Server-Sent Events) infrastructure for real-time push notifications.

Replaces frontend polling with event-driven updates via Redis pub/sub fan-out.
Each backend mutation publishes a lightweight signal to Redis; the SSEConnectionManager
subscribes to sse:* channels and fans out to connected clients.

Usage:
    # In mutation endpoints (fire-and-forget):
    from app.core.sse import sse_publish
    await sse_publish("etiquetas:changed", {"hint": "reload"})

    # In main.py lifespan:
    from app.core.sse import SSEConnectionManager, set_redis
    set_redis(redis_client)
    manager = SSEConnectionManager(redis_client, max_connections=100)
    await manager.start()
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)


# ── SSE Event Model ─────────────────────────────────────────────


class SSEEvent(BaseModel):
    """Pydantic model for SSE event payload (the `data` field in SSE protocol)."""

    channel: str
    data: dict[str, Any]
    timestamp: str

    model_config = ConfigDict(frozen=True)

    @classmethod
    def create(cls, channel: str, data: dict[str, Any] | None = None) -> SSEEvent:
        return cls(
            channel=channel,
            data=data or {},
            timestamp=datetime.now(UTC).isoformat(),
        )


# ── Redis reference + publish utility ────────────────────────────

_redis: Redis | None = None


def set_redis(redis_client: Redis) -> None:
    """Called from main.py lifespan to inject the Redis connection."""
    global _redis
    _redis = redis_client


async def sse_publish(channel: str, data: dict[str, Any] | None = None) -> None:
    """
    Publish an SSE notification event to Redis pub/sub.

    Fire-and-forget: if Redis is unavailable or no subscribers exist,
    the event is silently dropped.  This is intentional — SSE is best-effort
    and MUST NEVER block the primary mutation.

    Args:
        channel: Channel name (e.g., "etiquetas:changed", "alertas:updated")
        data: Optional dict payload (e.g., {"hint": "reload"}, {"count": 5})
    """
    if _redis is None:
        logger.warning("sse_publish called but Redis not initialized (channel=%s)", channel)
        return

    event = SSEEvent.create(channel=channel, data=data)
    redis_channel = f"sse:{channel}"

    try:
        await _redis.publish(redis_channel, event.model_dump_json())
    except Exception:
        logger.exception("Failed to publish SSE event (channel=%s)", channel)
        # Swallow — SSE is best-effort, never block the mutation


def sse_publish_bg(channel: str, data: dict[str, Any] | None = None) -> None:
    """
    Synchronous wrapper for sse_publish — for use from sync (def) endpoints.

    Runs the async publish in the running event loop via asyncio.ensure_future.
    Safe to call from FastAPI sync endpoints running in a thread pool because
    Starlette copies the event loop reference into the thread.
    If no loop is available, logs a warning and returns silently.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(sse_publish(channel, data))
        else:
            loop.run_until_complete(sse_publish(channel, data))
    except RuntimeError:
        logger.warning("sse_publish_bg: no event loop available (channel=%s)", channel)


# ── Connection Manager ───────────────────────────────────────────


class _ClientConnection:
    """Internal: tracks a single SSE client's subscribed channels and event queue."""

    __slots__ = ("channels", "queue")

    def __init__(self, channels: set[str], queue: asyncio.Queue) -> None:
        self.channels = channels
        self.queue = queue


class SSEConnectionManager:
    """
    Manages active SSE client connections and Redis pub/sub fan-out.

    Lifecycle:
    - Created in main.py lifespan startup
    - start() launches the Redis subscriber background task
    - stop() cancels the subscriber and cleans up all connections
    - register()/unregister() called per SSE endpoint request

    Thread safety: all methods are async and run on the same event loop.
    """

    def __init__(self, redis: Redis, max_connections: int = 100) -> None:
        self._redis = redis
        self._max_connections = max_connections
        # OrderedDict for LRU eviction: oldest connections evicted first
        self._connections: OrderedDict[str, _ClientConnection] = OrderedDict()
        self._subscriber_task: asyncio.Task | None = None
        self._event_id: int = 0  # Monotonic event ID counter

    async def start(self) -> None:
        """Start the Redis subscriber background task."""
        self._subscriber_task = asyncio.create_task(self._redis_subscriber())
        logger.info("SSE connection manager started (max_connections=%d)", self._max_connections)

    async def stop(self) -> None:
        """Stop subscriber and close all connections."""
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
        for conn in list(self._connections.values()):
            try:
                conn.queue.put_nowait(None)  # Signal generators to stop
            except asyncio.QueueFull:
                pass
        self._connections.clear()
        logger.info("SSE connection manager stopped")

    def register(self, channels: list[str]) -> tuple[str, asyncio.Queue]:
        """
        Register a new SSE client connection.

        Returns:
            (client_id, queue) — caller reads from queue to yield SSE events.

        At capacity, the oldest connection is evicted (LRU).
        """
        while len(self._connections) >= self._max_connections:
            oldest_id, oldest_conn = self._connections.popitem(last=False)
            try:
                oldest_conn.queue.put_nowait(None)  # Signal to close
            except asyncio.QueueFull:
                pass
            logger.warning(
                "SSE: evicted oldest connection %s (capacity=%d)",
                oldest_id,
                self._max_connections,
            )

        client_id = str(uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._connections[client_id] = _ClientConnection(
            channels=set(channels),
            queue=queue,
        )
        return client_id, queue

    def unregister(self, client_id: str) -> None:
        """Remove a client connection (called on disconnect)."""
        self._connections.pop(client_id, None)

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    def _next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    async def _redis_subscriber(self) -> None:
        """Background task: subscribe to sse:* channels and fan out to clients."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe("sse:*")
        logger.info("SSE: Redis subscriber started (pattern=sse:*)")

        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue

                redis_channel: str | bytes = message["channel"]
                if isinstance(redis_channel, bytes):
                    redis_channel = redis_channel.decode()

                # "sse:etiquetas:changed" → "etiquetas:changed"
                channel = redis_channel.removeprefix("sse:")
                raw_data = message["data"]
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode()

                event_id = self._next_event_id()

                # Fan out to all clients subscribed to this channel
                for client_id, conn in list(self._connections.items()):
                    if channel in conn.channels:
                        sse_payload = f"id: {event_id}\nevent: {channel}\ndata: {raw_data}\n\n"
                        try:
                            conn.queue.put_nowait(sse_payload)
                        except asyncio.QueueFull:
                            logger.warning(
                                "SSE: queue full for client %s, dropping event",
                                client_id,
                            )
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.punsubscribe("sse:*")
            await pubsub.aclose()
