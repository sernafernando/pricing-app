"""
Integration tests — routers/ml_bot.py (Slice F: API endpoints + permission
enforcement).

Covers:
- Every endpoint enforces its documented `ml_bot.*` permission code (403
  without it, 200/201/204 with it) independent of frontend state.
- take-over CAS never steals a row mid-publish (`publishing` excluded).
- publish-now resets `attempts=0` entering `waiting` (fresh publish budget,
  including the failed->waiting manual-retry path) and delegates to
  `publisher_service.publish_question_now()`.
- answer edit only allowed on `taken_over` rows.
- config/toggle/examples CRUD round-trips.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.ml_bot_answer_example import MlBotAnswerExample
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion

BASE = "/api/ml-bot"


# ==========================================================================
# Permission fixtures (same pattern as test_administracion_bancos_router.py)
# ==========================================================================


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


# ==========================================================================
# Data fixtures
# ==========================================================================

_next_ml_question_id = iter(range(9000, 9_000_000))


def _seed_question(db, *, status: str = "waiting", **overrides) -> MlBotQuestion:
    now = datetime.now(timezone.utc)
    defaults = dict(
        ml_question_id=next(_next_ml_question_id),
        item_id="MLA123456",
        buyer_id=1,
        buyer_nickname="comprador_test",
        question_text="¿Tienen stock?",
        question_date=now,
        status=status,
        drafted_answer="¡Hola! Sí, tenemos stock disponible." if status != "received" else None,
        attempts=overrides.pop("attempts", 0),
        wait_until=overrides.pop("wait_until", now - timedelta(minutes=1)),
    )
    defaults.update(overrides)
    q = MlBotQuestion(**defaults)
    db.add(q)
    db.flush()
    return q


# ==========================================================================
# GET /questions
# ==========================================================================


class TestListQuestions:
    def test_sin_token_401_o_403(self, client) -> None:
        r = client.get(f"{BASE}/questions")
        assert r.status_code in (401, 403)

    def test_sin_permiso_ver_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.get(f"{BASE}/questions", headers=auth_headers)
        assert r.status_code == 403

    def test_con_permiso_ver_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_question(db, status="waiting")
        _seed_question(db, status="published")
        db.commit()

        r = client.get(f"{BASE}/questions", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2

    def test_filtra_por_status(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_question(db, status="waiting")
        _seed_question(db, status="published")
        db.commit()

        r = client.get(f"{BASE}/questions?status=waiting", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["questions"][0]["status"] == "waiting"


# ==========================================================================
# POST /questions/{id}/take-over
# ==========================================================================


class TestTakeOver:
    def test_sin_permiso_responder_403(self, client, auth_headers, db, sin_permisos) -> None:
        q = _seed_question(db, status="waiting")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 403

    def test_solo_ver_no_alcanza_403(self, client, auth_headers, db) -> None:
        q = _seed_question(db, status="waiting")
        db.commit()
        with _permiso_solo("ml_bot.ver"):
            r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 403

    def test_toma_desde_waiting_200(self, client, auth_headers, db, active_user, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="waiting")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "taken_over"
        assert body["taken_over_by"] == active_user.id

    def test_toma_desde_pending_morning_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="pending_morning")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 200

    def test_toma_desde_failed_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="failed", attempts=3)
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 200

    def test_no_puede_robar_publishing_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """CAS never matches `publishing` — a row the background publisher
        has claimed mid-POST can never be stolen by a panel take-over."""
        q = _seed_question(db, status="publishing")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 409

    def test_ya_publicada_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="published")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/take-over", headers=auth_headers)
        assert r.status_code == 409

    def test_inexistente_404(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.post(f"{BASE}/questions/999999/take-over", headers=auth_headers)
        assert r.status_code == 404


# ==========================================================================
# PUT /questions/{id}/answer
# ==========================================================================


class TestEditAnswer:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()
        r = client.put(f"{BASE}/questions/{q.id}/answer", json={"drafted_answer": "Editado"}, headers=auth_headers)
        assert r.status_code == 403

    def test_edita_taken_over_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()
        r = client.put(
            f"{BASE}/questions/{q.id}/answer",
            json={"drafted_answer": "Respuesta editada por humano"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["drafted_answer"] == "Respuesta editada por humano"
        assert body["answer_source"] == "human"

    def test_no_permite_editar_waiting_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """Must take over before editing — the bot's own draft can't be
        mutated out from under an in-flight pipeline stage."""
        q = _seed_question(db, status="waiting")
        db.commit()
        r = client.put(f"{BASE}/questions/{q.id}/answer", json={"drafted_answer": "x"}, headers=auth_headers)
        assert r.status_code == 409

    def test_texto_vacio_422(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()
        r = client.put(f"{BASE}/questions/{q.id}/answer", json={"drafted_answer": ""}, headers=auth_headers)
        assert r.status_code == 422


# ==========================================================================
# POST /questions/{id}/publish-now
# ==========================================================================


class TestPublishNow:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/publish-now", headers=auth_headers)
        assert r.status_code == 403

    def test_publica_desde_taken_over(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()

        with patch(
            "app.services.ml_questions.publisher_service.publish_question_now",
            new_callable=AsyncMock,
            return_value="published",
        ) as mock_publish:
            r = client.post(f"{BASE}/questions/{q.id}/publish-now", headers=auth_headers)

        assert r.status_code == 200
        mock_publish.assert_awaited_once_with(q.id)

    def test_retry_de_failed_resetea_attempts(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """Judgment Day note: retrying a `failed` row (failed -> waiting)
        MUST reset attempts=0 — entering waiting is always a fresh publish
        budget."""
        q = _seed_question(db, status="failed", attempts=3, last_error="boom")
        db.commit()
        q_id = q.id

        with patch(
            "app.services.ml_questions.publisher_service.publish_question_now",
            new_callable=AsyncMock,
            return_value="published",
        ):
            r = client.post(f"{BASE}/questions/{q_id}/publish-now", headers=auth_headers)

        assert r.status_code == 200
        db.expire_all()
        refreshed = db.query(MlBotQuestion).filter(MlBotQuestion.id == q_id).first()
        assert refreshed.attempts == 0

    def test_sin_respuesta_cargada_400(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="waiting", drafted_answer=None)
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/publish-now", headers=auth_headers)
        assert r.status_code == 400

    def test_desde_publishing_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="publishing")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/publish-now", headers=auth_headers)
        assert r.status_code == 409


# ==========================================================================
# POST /questions/{id}/hold
# ==========================================================================


class TestHold:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        q = _seed_question(db, status="waiting")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/hold", headers=auth_headers)
        assert r.status_code == 403

    def test_retiene_desde_waiting_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="waiting")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/hold", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "pending_morning"

    def test_retiene_desde_taken_over_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="taken_over")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/hold", headers=auth_headers)
        assert r.status_code == 200

    def test_no_retiene_published_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        q = _seed_question(db, status="published")
        db.commit()
        r = client.post(f"{BASE}/questions/{q.id}/hold", headers=auth_headers)
        assert r.status_code == 409


# ==========================================================================
# GET/PUT /config
# ==========================================================================


class TestConfig:
    def test_get_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.get(f"{BASE}/config", headers=auth_headers)
        assert r.status_code == 403

    def test_get_con_permiso_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MlBotConfig(clave="wait_minutes", valor="5", tipo="int"))
        db.commit()
        r = client.get(f"{BASE}/config", headers=auth_headers)
        assert r.status_code == 200
        claves = [i["clave"] for i in r.json()["items"]]
        assert "wait_minutes" in claves

    def test_put_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.put(f"{BASE}/config/wait_minutes", json={"valor": "10", "tipo": "int"}, headers=auth_headers)
        assert r.status_code == 403

    def test_put_crea_si_no_existe(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.put(
            f"{BASE}/config/approx_address",
            json={"valor": "Zona Norte", "descripcion": "Zona aproximada", "tipo": "string"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["valor"] == "Zona Norte"

    def test_put_actualiza_existente(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MlBotConfig(clave="wait_minutes", valor="5", tipo="int"))
        db.commit()
        r = client.put(f"{BASE}/config/wait_minutes", json={"valor": "10", "tipo": "int"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["valor"] == "10"

    def test_put_valor_vacio_422(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.put(f"{BASE}/config/wait_minutes", json={"valor": ""}, headers=auth_headers)
        assert r.status_code == 422


# ==========================================================================
# POST /toggle
# ==========================================================================


class TestToggle:
    def test_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.post(f"{BASE}/toggle", json={"enabled": True}, headers=auth_headers)
        assert r.status_code == 403

    def test_solo_config_no_alcanza_403(self, client, auth_headers) -> None:
        with _permiso_solo("ml_bot.config"):
            r = client.post(f"{BASE}/toggle", json={"enabled": True}, headers=auth_headers)
        assert r.status_code == 403

    def test_prende_bot_200(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.post(f"{BASE}/toggle", json={"enabled": True}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["bot_enabled"] is True

    def test_apaga_bot_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MlBotConfig(clave="bot_enabled", valor="true", tipo="bool"))
        db.commit()
        r = client.post(f"{BASE}/toggle", json={"enabled": False}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["bot_enabled"] is False


# ==========================================================================
# GET/POST/DELETE /examples
# ==========================================================================


class TestExamples:
    def test_get_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.get(f"{BASE}/examples", headers=auth_headers)
        assert r.status_code == 403

    def test_get_con_permiso_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        db.add(MlBotAnswerExample(question_example="¿Stock?", answer_example="Sí, hay.", category="stock"))
        db.commit()
        r = client.get(f"{BASE}/examples", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()["examples"]) == 1

    def test_post_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.post(
            f"{BASE}/examples",
            json={"question_example": "q", "answer_example": "a"},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_post_crea_201(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.post(
            f"{BASE}/examples",
            json={
                "question_example": "¿Es compatible?",
                "answer_example": "Sí, es compatible.",
                "category": "compatibility",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["category"] == "compatibility"

    def test_delete_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        ex = MlBotAnswerExample(question_example="q", answer_example="a")
        db.add(ex)
        db.commit()
        r = client.delete(f"{BASE}/examples/{ex.id}", headers=auth_headers)
        assert r.status_code == 403

    def test_delete_existente_204(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        ex = MlBotAnswerExample(question_example="q", answer_example="a")
        db.add(ex)
        db.commit()
        r = client.delete(f"{BASE}/examples/{ex.id}", headers=auth_headers)
        assert r.status_code == 204

    def test_delete_inexistente_404(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.delete(f"{BASE}/examples/999999", headers=auth_headers)
        assert r.status_code == 404
