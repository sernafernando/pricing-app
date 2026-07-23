"""
Integration tests — routers/ml_bot.py messages take-over/answer/send
endpoints (ml-bot-messages-reply Phase A, PR2).

Mirrors `test_ml_bot_router.py`'s `TestTakeOver`/`TestEditAnswer` patterns
(same permission-fixture shape) but on the messages `bot_status` column and
its OWN permission (`ml_bot.messages.responder`). Also covers:
- `send-now` fail-closed (409) when `messages_send_enabled=False` (default).
- send success -> `sent`; permanent 4xx -> `failed` + `last_error`;
  transient (None) -> stays `taken_over` for manual retry.
- the never-auto-send invariant: nothing in this router calls
  `ml_client.send_message` except the explicit `/send` endpoint.
- nickname enrichment on `GET /messages` batches a single lookup query.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_message import MlBotMessage
from app.models.mercadolibre_user_data import MercadoLibreUserData
from app.services.ml_api_client import MessageSendPermanentError

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


def _permiso_solo(permiso_ok: str):
    return patch(
        "app.services.permisos_service.PermisosService.tiene_permiso",
        side_effect=lambda self_or_user, *args, **kwargs: args[0] == permiso_ok if args else False,
    )


def _enable_send(db) -> None:
    db.add(MlBotConfig(clave="messages_send_enabled", valor="true", tipo="bool"))
    db.flush()


_next_ml_message_id = iter(range(9000, 9_000_000))


def _seed_message(db, *, bot_status=None, **overrides) -> MlBotMessage:
    now = datetime.now(timezone.utc)
    defaults = dict(
        ml_message_id=f"msg-{next(_next_ml_message_id)}",
        pack_id="PACK123",
        buyer_id=1,
        buyer_nickname=None,
        seller_id=413658225,
        subject=None,
        text="Hola, ¿tienen stock?",
        status="available",
        received_at=now,
        bot_status=bot_status,
        drafted_answer="Sí, tenemos stock." if bot_status in ("awaiting_human", "taken_over") else None,
    )
    defaults.update(overrides)
    m = MlBotMessage(**defaults)
    db.add(m)
    db.flush()
    return m


# ==========================================================================
# POST /messages/{id}/take-over
# ==========================================================================


class TestTakeOverMessage:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        m = _seed_message(db, bot_status="awaiting_human")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 403

    def test_solo_ver_no_alcanza_403(self, client, auth_headers, db) -> None:
        m = _seed_message(db, bot_status="awaiting_human")
        db.commit()
        with _permiso_solo("ml_bot.messages.ver"):
            r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 403

    def test_toma_desde_awaiting_human_200(self, client, auth_headers, db, active_user, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="awaiting_human")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["bot_status"] == "taken_over"
        assert body["taken_over_by"] == active_user.id

    def test_toma_desde_blocked_claim_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="blocked_claim")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["bot_status"] == "taken_over"

    def test_toma_desde_failed_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """`failed` (permanent send failure) must be recoverable, mirroring
        `tomar_pregunta` — otherwise a permanently-failed send is a dead end
        with no UI path out (review finding, Phase A FE)."""
        m = _seed_message(db, bot_status="failed")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["bot_status"] == "taken_over"

    def test_no_puede_robar_drafting_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="drafting")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 409

    def test_ya_tomado_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/take-over", headers=auth_headers)
        assert r.status_code == 409

    def test_inexistente_404(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.post(f"{BASE}/messages/999999/take-over", headers=auth_headers)
        assert r.status_code == 404


# ==========================================================================
# PUT /messages/{id}/answer
# ==========================================================================


class TestEditMessageAnswer:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        db.commit()
        r = client.put(f"{BASE}/messages/{m.id}/answer", json={"drafted_answer": "Editado"}, headers=auth_headers)
        assert r.status_code == 403

    def test_edita_taken_over_con_borrador_previo_human_edited(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        m = _seed_message(db, bot_status="taken_over")
        db.commit()
        r = client.put(
            f"{BASE}/messages/{m.id}/answer",
            json={"drafted_answer": "Respuesta editada por humano"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["drafted_answer"] == "Respuesta editada por humano"
        assert body["answer_source"] == "human_edited"

    def test_edita_taken_over_sin_borrador_previo_human_verbatim(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        m = _seed_message(db, bot_status="taken_over", drafted_answer=None)
        db.commit()
        r = client.put(
            f"{BASE}/messages/{m.id}/answer",
            json={"drafted_answer": "Escrito desde cero"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["answer_source"] == "human_verbatim"

    def test_no_permite_editar_awaiting_human_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="awaiting_human")
        db.commit()
        r = client.put(f"{BASE}/messages/{m.id}/answer", json={"drafted_answer": "x"}, headers=auth_headers)
        assert r.status_code == 409

    def test_texto_vacio_422(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        db.commit()
        r = client.put(f"{BASE}/messages/{m.id}/answer", json={"drafted_answer": ""}, headers=auth_headers)
        assert r.status_code == 422


# ==========================================================================
# POST /messages/{id}/send
# ==========================================================================


class TestSendMessage:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        db.commit()
        r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)
        assert r.status_code == 403

    def test_disabled_by_default_returns_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """R-8/R-8.2: fail-closed while `messages_send_enabled` is off
        (default), independent of any live-verify status."""
        m = _seed_message(db, bot_status="taken_over")
        db.commit()

        with patch(
            "app.services.ml_api_client.MercadoLibreAPIClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)

        assert r.status_code == 409
        mock_send.assert_not_called()

    def test_send_success_sets_sent(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        _enable_send(db)
        db.commit()

        with patch(
            "app.services.ml_api_client.MercadoLibreAPIClient.send_message",
            new_callable=AsyncMock,
            return_value={"id": "msg-sent"},
        ) as mock_send:
            r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["sent"] is True
        assert body["message"]["bot_status"] == "sent"
        mock_send.assert_awaited_once_with("PACK123", 1, "Sí, tenemos stock.", seller_id=413658225)

    def test_send_permanent_error_sets_failed_with_last_error(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        m = _seed_message(db, bot_status="taken_over")
        _enable_send(db)
        db.commit()

        with patch(
            "app.services.ml_api_client.MercadoLibreAPIClient.send_message",
            new_callable=AsyncMock,
            side_effect=MessageSendPermanentError("PACK123", 422, "invalid buyer"),
        ):
            r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["sent"] is False
        assert body["message"]["bot_status"] == "failed"
        assert "invalid buyer" in body["message"]["last_error"]

    def test_send_transient_failure_stays_taken_over(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over")
        _enable_send(db)
        db.commit()

        with patch(
            "app.services.ml_api_client.MercadoLibreAPIClient.send_message",
            new_callable=AsyncMock,
            return_value=None,
        ):
            r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["sent"] is False
        assert body["message"]["bot_status"] == "taken_over"

    def test_not_taken_over_returns_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="awaiting_human")
        _enable_send(db)
        db.commit()

        with patch(
            "app.services.ml_api_client.MercadoLibreAPIClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)

        assert r.status_code == 409
        mock_send.assert_not_called()

    def test_no_drafted_answer_returns_400(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        m = _seed_message(db, bot_status="taken_over", drafted_answer=None)
        _enable_send(db)
        db.commit()

        r = client.post(f"{BASE}/messages/{m.id}/send", headers=auth_headers)
        assert r.status_code == 400


# ==========================================================================
# GET /messages nickname enrichment
# ==========================================================================


class TestMessageNicknameEnrichment:
    def test_nickname_looked_up_from_users_data_table(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MercadoLibreUserData(mluser_id=42, nickname="COMPRADOR_REAL"))
        db.flush()
        _seed_message(db, buyer_id=42, buyer_nickname=None)
        db.commit()

        r = client.get(f"{BASE}/messages", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["messages"][0]["buyer_nickname"] == "COMPRADOR_REAL"

    def test_missing_users_data_row_falls_back_to_stored_or_none(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        _seed_message(db, buyer_id=999999, buyer_nickname=None)
        db.commit()

        r = client.get(f"{BASE}/messages", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["messages"][0]["buyer_nickname"] is None

    def test_batches_single_lookup_query_no_n_plus_1(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MercadoLibreUserData(mluser_id=1, nickname="COMPRADOR_1"))
        db.add(MercadoLibreUserData(mluser_id=2, nickname="COMPRADOR_2"))
        db.flush()
        _seed_message(db, buyer_id=1, buyer_nickname=None)
        _seed_message(db, buyer_id=2, buyer_nickname=None)
        db.commit()

        from app.routers import ml_bot as ml_bot_router

        original_enrich = ml_bot_router._enrich_message_nicknames
        call_count = {"n": 0}

        def counting_enrich(db_arg, rows):
            call_count["n"] += 1
            return original_enrich(db_arg, rows)

        with patch.object(ml_bot_router, "_enrich_message_nicknames", side_effect=counting_enrich):
            r = client.get(f"{BASE}/messages", headers=auth_headers)

        assert r.status_code == 200
        assert call_count["n"] == 1  # one batched call for the whole list, not per-row
        nicknames = {m["buyer_nickname"] for m in r.json()["messages"]}
        assert nicknames == {"COMPRADOR_1", "COMPRADOR_2"}
