"""
Integration tests — routers/ml_bot.py GET /api/ml-bot/messages (PR2 of the
ml-bot-postventa-messages-mvp slice).

Mirrors `test_ml_bot_router.py`'s `TestListQuestions` fixtures/pattern:
- Permission enforcement via `ml_bot.messages.ver`.
- Filters: status, buyer_id, pack_id (incl. `none` sentinel), has_read,
  include_moderated (default hides non-clean, NULL always shown).
- Pagination (limit/offset), ordered by `received_at DESC`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.ml_bot_message import MlBotMessage

BASE = "/api/ml-bot"


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


_next_ml_message_id = iter(range(9000, 9_000_000))


def _seed_message(db, *, received_at=None, **overrides) -> MlBotMessage:
    now = received_at or datetime.now(timezone.utc)
    defaults = dict(
        ml_message_id=f"msg-{next(_next_ml_message_id)}",
        pack_id="PACK123",
        buyer_id=1,
        buyer_nickname="comprador_test",
        seller_id=413658225,
        subject=None,
        text="Hola, ¿tienen stock?",
        status="available",
        moderation_status=None,
        is_first_message=False,
        received_at=now,
        read_at=None,
        kind="postventa",
    )
    defaults.update(overrides)
    m = MlBotMessage(**defaults)
    db.add(m)
    db.flush()
    return m


class TestListMessages:
    def test_get_messages_returns_403_without_permission(self, client, auth_headers, sin_permisos) -> None:
        r = client.get(f"{BASE}/messages", headers=auth_headers)
        assert r.status_code == 403

    def test_get_messages_returns_200_with_permission(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_message(db)
        _seed_message(db)
        db.commit()

        r = client.get(f"{BASE}/messages", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["messages"]) == 2

    def test_get_messages_status_filter(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_message(db, status="available")
        _seed_message(db, status="blocked")
        db.commit()

        r = client.get(f"{BASE}/messages?status=available", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["messages"][0]["status"] == "available"

    def test_get_messages_buyer_id_filter(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_message(db, buyer_id=111)
        _seed_message(db, buyer_id=222)
        db.commit()

        r = client.get(f"{BASE}/messages?buyer_id=111", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["messages"][0]["buyer_id"] == 111

    def test_get_messages_pack_id_filter(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_message(db, pack_id="PACKA")
        _seed_message(db, pack_id="PACKB")
        db.commit()

        r = client.get(f"{BASE}/messages?pack_id=PACKA", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["messages"][0]["pack_id"] == "PACKA"

    def test_get_messages_unassigned_filter(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_message(db, pack_id=None)
        _seed_message(db, pack_id="PACKB")
        db.commit()

        r = client.get(f"{BASE}/messages?pack_id=none", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["messages"][0]["pack_id"] is None

    def test_get_messages_has_read_filter(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        now = datetime.now(timezone.utc)
        _seed_message(db, read_at=now)
        _seed_message(db, read_at=None)
        db.commit()

        r_true = client.get(f"{BASE}/messages?has_read=true", headers=auth_headers)
        assert r_true.status_code == 200
        assert r_true.json()["total"] == 1
        assert r_true.json()["messages"][0]["read_at"] is not None

        r_false = client.get(f"{BASE}/messages?has_read=false", headers=auth_headers)
        assert r_false.status_code == 200
        assert r_false.json()["total"] == 1
        assert r_false.json()["messages"][0]["read_at"] is None

    def test_get_messages_include_moderated_flag_hides_by_default_shows_when_true(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        _seed_message(db, moderation_status=None)
        _seed_message(db, moderation_status="clean")
        _seed_message(db, moderation_status="pending")
        db.commit()

        r_default = client.get(f"{BASE}/messages", headers=auth_headers)
        assert r_default.status_code == 200
        assert r_default.json()["total"] == 2

        r_include = client.get(f"{BASE}/messages?include_moderated=true", headers=auth_headers)
        assert r_include.status_code == 200
        assert r_include.json()["total"] == 3

    def test_get_messages_pagination(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        now = datetime.now(timezone.utc)
        for i in range(5):
            _seed_message(db, received_at=now - timedelta(minutes=i))
        db.commit()

        r = client.get(f"{BASE}/messages?limit=2&offset=1", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 5
        assert len(body["messages"]) == 2
