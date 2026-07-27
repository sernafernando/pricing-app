"""
Regression tests for `20260727_fix_llm_model_ids` — the migration that
corrects the cerebras/openrouter model ids in the `llm_providers` roster.

The bug these lock down: an unknown model id answers 4xx, which
`OpenAICompatProvider` treats as a permanent error (no retry), so
`RotatingProvider` fails over and groq — the only id that resolved — absorbed
100% of the traffic. Nothing crashed and nothing looked wrong except the
provider distribution, which is why it went unnoticed.

Model ids here were verified against each provider's live catalogue AND with
a real chat-completions call using the payload shape the bot sends.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260727_fix_llm_model_ids.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("fix_llm_model_ids", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration():
    return _load_migration()


class TestFixedRosterContents:
    def test_all_three_providers_present_and_enabled(self, migration) -> None:
        roster = json.loads(migration.FIXED_ROSTER)
        assert [entry["name"] for entry in roster] == ["groq", "cerebras", "openrouter"]
        assert all(entry["enabled"] is True for entry in roster)

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("groq", "llama-3.3-70b-versatile"),
            ("cerebras", "gpt-oss-120b"),
            ("openrouter", "openai/gpt-oss-20b:free"),
        ],
    )
    def test_verified_model_ids(self, migration, provider: str, model: str) -> None:
        roster = {entry["name"]: entry["model"] for entry in json.loads(migration.FIXED_ROSTER)}
        assert roster[provider] == model

    def test_retired_openrouter_free_variant_is_gone(self, migration) -> None:
        """`meta-llama/llama-3.3-70b-instruct:free` no longer exists in the
        OpenRouter catalogue; it must not come back."""
        assert ":free" not in migration.FIXED_ROSTER.replace("openai/gpt-oss-20b:free", "")
        assert "llama-3.3-70b-instruct" not in migration.FIXED_ROSTER

    def test_cerebras_no_longer_points_at_a_llama(self, migration) -> None:
        roster = {entry["name"]: entry["model"] for entry in json.loads(migration.FIXED_ROSTER)}
        assert "llama" not in roster["cerebras"]


class TestConditionalUpdatePreservesCustomisation:
    def test_broken_constant_matches_the_original_seed_byte_for_byte(self, migration) -> None:
        """The UPDATE is gated on this exact string. If the 20260708 seed ever
        changes, this migration silently becomes a no-op — so pin it."""
        seed = (
            Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260708_ml_bot_roster_seed.py"
        ).read_text(encoding="utf-8")
        for fragment in (
            '{"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true}',
            '{"name": "cerebras", "model": "llama-3.3-70b", "enabled": true}',
            '{"name": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "enabled": true}',
        ):
            assert fragment in seed
            assert fragment in migration.BROKEN_ROSTER

    def test_upgrade_is_scoped_to_the_broken_value(self, migration) -> None:
        """A hand-edited roster must survive the migration untouched."""
        import inspect

        source = inspect.getsource(migration.upgrade)
        assert "AND valor = :broken" in source
        assert "clave = 'llm_providers'" in source


class TestRosterParsesWithTheRotationLoader:
    def test_fixed_roster_yields_three_usable_entries(self, migration, monkeypatch) -> None:
        """End-to-end through the real loader: the corrected JSON must produce
        three enabled entries, not fall back to the Groq-only fail-safe."""
        from app.services.ml_questions import provider_rotation

        monkeypatch.setattr(
            provider_rotation.policy,
            "get_config",
            lambda db, key, cast=str, default=None: migration.FIXED_ROSTER if key == "llm_providers" else default,
        )

        entries = provider_rotation._load_roster_entries(db=None)
        assert [e["name"] for e in entries] == ["groq", "cerebras", "openrouter"]
        assert [e["model"] for e in entries] == [
            "llama-3.3-70b-versatile",
            "gpt-oss-120b",
            "openai/gpt-oss-20b:free",
        ]


class TestCodeDefaultsMatchTheVerifiedIds:
    """The migration only fixes rows that carry an explicit `model`. A roster
    entry omitting it falls back to `_known_provider_specs`, so those defaults
    must name the same verified ids — otherwise the bug simply moves.
    """

    def test_defaults_are_the_verified_model_ids(self, migration) -> None:
        from app.services.ml_questions import provider_rotation

        specs = provider_rotation._known_provider_specs()
        expected = {entry["name"]: entry["model"] for entry in json.loads(migration.FIXED_ROSTER)}
        for name, model in expected.items():
            assert specs[name].default_model == model, f"default_model for {name} drifted from the verified roster"

    def test_no_default_points_at_a_retired_id(self, migration) -> None:
        from app.services.ml_questions import provider_rotation

        specs = provider_rotation._known_provider_specs()
        retired = {"llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct:free"}
        assert not ({spec.default_model for spec in specs.values()} & retired)

    def test_entry_without_model_resolves_to_a_verified_id(self, monkeypatch) -> None:
        """End-to-end through the real builder: `{"name": "cerebras"}` with no
        `model` key must produce a provider pointing at a valid id."""
        from app.services.ml_questions import provider_rotation

        specs = provider_rotation._known_provider_specs()
        provider = provider_rotation._build_provider({"name": "cerebras", "model": None}, specs)
        assert provider is not None
        assert provider.model == "gpt-oss-120b"
