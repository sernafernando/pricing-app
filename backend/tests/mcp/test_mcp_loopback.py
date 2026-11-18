"""In-process calls must never look local: deps that trust localhost (scripts, crons) would skip login."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request

from app.api.deps import LOCALHOST_IPS
from app.mcp import loopback


def test_loopback_calls_do_not_come_from_a_localhost_address(monkeypatch):
    probe = FastAPI()

    @probe.get("/whoami")
    def whoami(request: Request) -> dict:
        return {"host": request.client.host if request.client else None}

    monkeypatch.setattr(loopback, "_app_getter", lambda: probe)
    status, body = asyncio.run(loopback.send_request("/whoami", {}, {}))
    assert status == 200
    host = json.loads(body)["host"]
    assert host not in LOCALHOST_IPS
    assert host == loopback.LOOPBACK_CLIENT[0]
