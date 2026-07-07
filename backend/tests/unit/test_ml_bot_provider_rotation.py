"""
Unit tests — services/ml_questions/provider_rotation.py
(sdd/ml-questions-ai/provider-rotation follow-up to Slice D1/D2).

Covers:
- Roster parsing: valid, malformed JSON, non-list, unknown provider names,
  disabled entries, missing API keys -> fail-safe to Groq-only default.
- Rotation cursor: round-robin across N questions, persistence, fail-safe
  reset on malformed cursor value.
- Failover: first provider raises -> second provider answers.
- All-providers-fail -> `RotatingProvider.complete()` raises
  `LlmProviderError` (caller routes to warm fallback, never crashes).

No pytest-asyncio in this project — async code is driven with
`asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from unittest.mock import patch

from app.models.ml_bot_config import MlBotConfig
from app.services.ml_questions import provider_rotation
from app.services.ml_questions.llm_provider import LlmProviderError


class _ctx:
    """Same SAVEPOINT-based stub used by the drafting/ingestion tests, so
    `get_background_db()` reuses the test's transactional `db` fixture."""

    def __init__(self, db) -> None:
        self._db = db
        self._nested = None

    def __enter__(self):
        self._nested = self._db.begin_nested()
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._nested.commit()
        else:
            self._nested.rollback()
        return False


def _patch_db(db):
    return patch("app.services.ml_questions.provider_rotation.get_background_db", return_value=_ctx(db))


def _seed_config(db, clave: str, valor: str, tipo: str = "string") -> None:
    row = db.query(MlBotConfig).filter_by(clave=clave).first()
    if row is None:
        db.add(MlBotConfig(clave=clave, valor=valor, tipo=tipo))
    else:
        row.valor = valor
    db.flush()


def _all_keys_configured(monkeypatch) -> None:
    monkeypatch.setattr(provider_rotation.settings, "GROQ_API_KEY", "sk-groq")
    monkeypatch.setattr(provider_rotation.settings, "CEREBRAS_API_KEY", "sk-cerebras")
    monkeypatch.setattr(provider_rotation.settings, "OPENROUTER_API_KEY", "sk-openrouter")


class TestRosterParsing:
    def test_missing_roster_falls_back_to_groq_only(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_malformed_json_falls_back_to_groq_only(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, "not json {")
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_non_list_json_falls_back_to_groq_only(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps({"name": "groq"}))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_unknown_provider_name_skipped(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": True},
            {"name": "not-a-real-provider", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_disabled_entry_excluded(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": False},
            {"name": "cerebras", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["cerebras"]

    def test_missing_api_key_excludes_provider(self, db, monkeypatch) -> None:
        monkeypatch.setattr(provider_rotation.settings, "GROQ_API_KEY", "sk-groq")
        monkeypatch.setattr(provider_rotation.settings, "CEREBRAS_API_KEY", None)
        roster = [
            {"name": "groq", "enabled": True},
            {"name": "cerebras", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_per_provider_model_override(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [{"name": "cerebras", "model": "custom-model", "enabled": True}]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert providers[0]._model == "custom-model"

    def test_default_model_used_when_no_override(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [{"name": "cerebras", "enabled": True}]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert providers[0]._model == "llama-3.3-70b"

    def test_no_configured_providers_returns_empty_list(self, db, monkeypatch) -> None:
        monkeypatch.setattr(provider_rotation.settings, "GROQ_API_KEY", None)
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert providers == []

    def test_string_enabled_false_treated_as_malformed_and_skipped(self, db, monkeypatch, caplog) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": "false"},
            {"name": "cerebras", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        target_logger = logging.getLogger("app.services.ml_questions.provider_rotation")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            with _patch_db(db):
                providers = provider_rotation.available_providers(db)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert [p.name for p in providers] == ["cerebras"]
        assert any("groq" in record.getMessage() for record in caplog.records)

    def test_enabled_json_false_excludes_provider(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": False},
            {"name": "cerebras", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["cerebras"]

    def test_enabled_absent_defaults_to_true(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [{"name": "groq"}]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq"]

    def test_duplicate_roster_names_deduped(self, db, monkeypatch, caplog) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": True},
            {"name": "groq", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        target_logger = logging.getLogger("app.services.ml_questions.provider_rotation")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            with _patch_db(db):
                providers = provider_rotation.available_providers(db)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert [p.name for p in providers] == ["groq"]
        assert any("duplicate" in record.getMessage().lower() for record in caplog.records)

    def test_same_provider_different_model_not_deduped(self, db, monkeypatch) -> None:
        """Item #4 (PR de pulido): dedupe key is (name, model) — the SAME
        provider with DIFFERENT models is a valid roster variant, not a
        duplicate (fairness/fallback chain: groq-70b -> groq-8b)."""
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": True},
            {"name": "groq", "model": "llama-3.1-8b-instant", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            providers = provider_rotation.available_providers(db)

        assert [p.name for p in providers] == ["groq", "groq"]
        assert [p.model for p in providers] == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


class TestRotationCursor:
    def test_round_robin_across_n_questions(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [
            {"name": "groq", "enabled": True},
            {"name": "cerebras", "enabled": True},
            {"name": "openrouter", "enabled": True},
        ]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        first_choices = []
        with _patch_db(db):
            for _ in range(6):
                order = provider_rotation.build_rotation_order()
                first_choices.append(order[0].name)

        assert first_choices == ["groq", "cerebras", "openrouter", "groq", "cerebras", "openrouter"]

    def test_cursor_persists_across_calls(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        roster = [{"name": "groq", "enabled": True}, {"name": "cerebras", "enabled": True}]
        _seed_config(db, provider_rotation.ROSTER_CONFIG_KEY, json.dumps(roster))
        db.commit()

        with _patch_db(db):
            provider_rotation.build_rotation_order()
            order = provider_rotation.build_rotation_order()

        assert order[0].name == "cerebras"

        row = db.query(MlBotConfig).filter_by(clave=provider_rotation.CURSOR_CONFIG_KEY).first()
        assert row.valor == "0"

    def test_malformed_cursor_value_resets_to_zero(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        _seed_config(db, provider_rotation.CURSOR_CONFIG_KEY, "not-an-int")
        db.commit()

        with _patch_db(db):
            order = provider_rotation.build_rotation_order()

        assert order[0].name == "groq"

    def test_cursor_wraps_when_roster_shrinks(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        _seed_config(db, provider_rotation.CURSOR_CONFIG_KEY, "5")
        db.commit()

        with _patch_db(db):
            order = provider_rotation.build_rotation_order()

        assert order[0].name == "groq"

    def test_empty_roster_returns_empty_order_without_touching_cursor(self, db, monkeypatch) -> None:
        monkeypatch.setattr(provider_rotation.settings, "GROQ_API_KEY", None)
        db.commit()

        with _patch_db(db):
            order = provider_rotation.build_rotation_order()

        assert order == []


class _FakeOkProvider:
    def __init__(self, name: str, response: str) -> None:
        self.name = name
        self._response = response

    def is_configured(self) -> bool:
        return True

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        return self._response


class _FakeFailingProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def is_configured(self) -> bool:
        return True

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        raise LlmProviderError(f"{self.name} exhausted")


class TestFailover:
    def test_first_provider_fails_second_answers(self, monkeypatch) -> None:
        providers = [_FakeFailingProvider("groq"), _FakeOkProvider("cerebras", "hola desde cerebras")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)

        rotating = provider_rotation.RotatingProvider()
        result = asyncio.run(rotating.complete("system", "user"))

        assert result == "hola desde cerebras"

    def test_all_providers_fail_raises_llm_provider_error(self, monkeypatch) -> None:
        providers = [_FakeFailingProvider("groq"), _FakeFailingProvider("cerebras")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)

        rotating = provider_rotation.RotatingProvider()
        with pytest.raises(LlmProviderError):
            asyncio.run(rotating.complete("system", "user"))

    def test_no_available_providers_raises_llm_provider_error(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: [])

        rotating = provider_rotation.RotatingProvider()
        with pytest.raises(LlmProviderError):
            asyncio.run(rotating.complete("system", "user"))

    def test_only_one_full_cycle_attempted(self, monkeypatch) -> None:
        calls = {"count": 0}

        class _CountingFailingProvider(_FakeFailingProvider):
            async def complete(self, system_prompt: str, user_payload: str) -> str:
                calls["count"] += 1
                raise LlmProviderError("nope")

        providers = [_CountingFailingProvider("groq"), _CountingFailingProvider("cerebras")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)

        rotating = provider_rotation.RotatingProvider()
        with pytest.raises(LlmProviderError):
            asyncio.run(rotating.complete("system", "user"))

        assert calls["count"] == len(providers)


class TestFailoverNotification:
    """Item #3 (PR de pulido): failover between providers (or all failing)
    creates a notification via the existing notification system, throttled
    to at most one per FAILED provider per hour."""

    def test_failover_creates_notification(self, db, monkeypatch) -> None:
        # Pre-seed the throttle row (an old timestamp -> not throttled) so
        # the write below is an UPDATE, not a fresh INSERT — avoids a
        # SAVEPOINT+RETURNING interaction with this test harness's
        # nested-transaction stub that otherwise corrupts the OUTER test
        # transaction's rollback (see ingestion test suite for the same
        # documented workaround).
        _seed_config(db, "llm_failover_notified_groq", "2020-01-01T00:00:00+00:00")
        providers = [_FakeFailingProvider("groq"), _FakeOkProvider("cerebras", "hola")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)
        monkeypatch.setattr(provider_rotation, "get_background_db", lambda: _ctx(db))

        created = {}

        def _fake_crear(session, *, permisos_requeridos, tipo, mensaje, severidad):
            created["permisos_requeridos"] = permisos_requeridos
            created["tipo"] = tipo
            created["mensaje"] = mensaje
            return []

        monkeypatch.setattr(
            "app.services.notificacion_service.crear_notificaciones_para_permisos", _fake_crear
        )

        asyncio.run(provider_rotation.RotatingProvider().complete("system", "user"))

        assert created["tipo"] == "ml_bot.llm_failover"
        assert "groq" in created["mensaje"]
        assert "cerebras" in created["mensaje"]
        assert created["permisos_requeridos"] == ["ml_bot.config"]

    def test_all_fail_creates_notification_without_coverage(self, db, monkeypatch) -> None:
        _seed_config(db, "llm_failover_notified_groq", "2020-01-01T00:00:00+00:00")
        providers = [_FakeFailingProvider("groq"), _FakeFailingProvider("cerebras")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)
        monkeypatch.setattr(provider_rotation, "get_background_db", lambda: _ctx(db))

        created = {}

        def _fake_crear(session, *, permisos_requeridos, tipo, mensaje, severidad):
            created["mensaje"] = mensaje
            return []

        monkeypatch.setattr(
            "app.services.notificacion_service.crear_notificaciones_para_permisos", _fake_crear
        )

        with pytest.raises(LlmProviderError):
            asyncio.run(provider_rotation.RotatingProvider().complete("system", "user"))

        assert "TODOS los proveedores" in created["mensaje"]

    def test_throttled_within_the_hour(self, db, monkeypatch) -> None:
        """A second failover for the SAME failed provider within an hour
        does not create a second notification."""
        _seed_config(db, "llm_failover_notified_groq", "2020-01-01T00:00:00+00:00")
        providers = [_FakeFailingProvider("groq"), _FakeOkProvider("cerebras", "hola")]
        monkeypatch.setattr(provider_rotation, "build_rotation_order", lambda: providers)
        monkeypatch.setattr(provider_rotation, "get_background_db", lambda: _ctx(db))

        call_count = {"n": 0}

        def _fake_crear(session, *, permisos_requeridos, tipo, mensaje, severidad):
            call_count["n"] += 1
            return []

        monkeypatch.setattr(
            "app.services.notificacion_service.crear_notificaciones_para_permisos", _fake_crear
        )

        asyncio.run(provider_rotation.RotatingProvider().complete("system", "user"))
        asyncio.run(provider_rotation.RotatingProvider().complete("system", "user"))

        assert call_count["n"] == 1


class TestRotatingProviderIsConfigured:
    def test_is_configured_true_when_any_provider_available(self, db, monkeypatch) -> None:
        _all_keys_configured(monkeypatch)
        db.commit()

        with _patch_db(db):
            assert provider_rotation.RotatingProvider().is_configured() is True

    def test_is_configured_false_when_none_available(self, db, monkeypatch) -> None:
        monkeypatch.setattr(provider_rotation.settings, "GROQ_API_KEY", None)
        db.commit()

        with _patch_db(db):
            assert provider_rotation.RotatingProvider().is_configured() is False
