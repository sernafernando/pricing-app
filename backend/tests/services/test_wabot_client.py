"""ml-sync-pipeline T5 (S5): the backend sends a WhatsApp to the owner through wabot.

wabot sends a message without `to` to the users' group, so a message for the owner is never sent without the
owner's recipient.
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.core.config import settings
from app.services import wabot_client


@pytest.fixture()
def posts(monkeypatch) -> List[Dict[str, Any]]:
    sent: List[Dict[str, Any]] = []

    def fake_post(url, *, json, headers, timeout):
        sent.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(wabot_client.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "WABOT_URL", "http://wabot.test:3000")
    monkeypatch.setattr(settings, "WABOT_TOKEN", "token-123")
    monkeypatch.setattr(settings, "WABOT_OWNER_TO", "5490000000000")
    return sent


class TestSendToOwner:
    def test_it_posts_the_message_to_the_owner(self, posts) -> None:
        assert wabot_client.send_to_owner("refresh is late") == "sent"

        assert posts == [
            {
                "url": "http://wabot.test:3000/send",
                "json": {"message": "refresh is late", "to": "5490000000000"},
                "headers": {"Authorization": "Bearer token-123"},
                "timeout": wabot_client.TIMEOUT_SECONDS,
            }
        ]

    @pytest.mark.parametrize("missing", ["WABOT_OWNER_TO", "WABOT_TOKEN", "WABOT_URL"])
    def test_without_recipient_token_or_url_nothing_is_sent(self, posts, monkeypatch, missing) -> None:
        monkeypatch.setattr(settings, missing, None)

        assert wabot_client.send_to_owner("refresh is late") == "not_configured"
        assert posts == []

    def test_a_refused_send_is_reported_not_raised(self, posts, monkeypatch) -> None:
        monkeypatch.setattr(
            wabot_client.httpx,
            "post",
            lambda url, **kw: httpx.Response(401, request=httpx.Request("POST", url)),
        )

        assert wabot_client.send_to_owner("refresh is late") == "failed: http 401"

    def test_an_unreachable_wabot_is_reported_not_raised(self, posts, monkeypatch) -> None:
        def down(url, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(wabot_client.httpx, "post", down)

        assert wabot_client.send_to_owner("refresh is late") == "failed: ConnectError"
