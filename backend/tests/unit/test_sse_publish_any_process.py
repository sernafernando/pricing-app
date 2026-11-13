"""`sse_publish_any_process`: sync code in the worker processes (no API event loop) still reaches the SSE clients."""

from __future__ import annotations

import asyncio
import json

import pytest
import redis

from app.core import sse


class _FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    def publish(self, channel: str, message: str) -> int:
        if self.fail:
            raise redis.ConnectionError("down")
        self.published.append((channel, message))
        return 1


@pytest.fixture()
def no_loop(monkeypatch):
    monkeypatch.setattr(sse, "_event_loop", None)  # a worker process: `set_redis` never ran
    yield
    sse._set_sync_client_for_tests(None)


def test_outside_the_api_it_publishes_straight_to_the_redis_channel(no_loop) -> None:
    fake = _FakeRedis()
    sse._set_sync_client_for_tests(fake)
    sse.sse_publish_any_process("ml-publications:mejores-ofertas", {"hint": "reload"})
    [(channel, message)] = fake.published
    assert channel == "sse:ml-publications:mejores-ofertas"  # the channel the API's manager fans out
    body = json.loads(message)
    assert body["channel"] == "ml-publications:mejores-ofertas" and body["data"] == {"hint": "reload"}


def test_a_redis_error_never_reaches_the_caller(no_loop, caplog) -> None:
    sse._set_sync_client_for_tests(_FakeRedis(fail=True))
    sse.sse_publish_any_process("ml-publications:mejores-ofertas")
    assert "SSE sync publish failed" in caplog.text


def test_inside_the_api_it_goes_through_the_event_loop(monkeypatch) -> None:
    calls: list[str] = []
    loop = asyncio.new_event_loop()
    try:
        monkeypatch.setattr(sse, "_event_loop", loop)
        monkeypatch.setattr(sse, "sse_publish_bg", lambda channel, data=None: calls.append(channel))
        sse._set_sync_client_for_tests(_FakeRedis(fail=True))
        sse.sse_publish_any_process("ml-publications:mejores-ofertas")
        assert calls == ["ml-publications:mejores-ofertas"]
    finally:
        sse._set_sync_client_for_tests(None)
        loop.close()
