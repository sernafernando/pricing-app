"""Default LLM model ids must exist at their provider.

An id the provider no longer serves answers 4xx, which `complete()` treats as
permanent (no retry): the ml-bot drops that provider from rotation silently,
and ticket triage, which has no rotation, simply stops working. Groq retired
the Llama models from its free tier on 2026-08-16, and OpenRouter withdrew
`openai/gpt-oss-20b:free`, so every default that still named them was dead.
"""

from app.services.ml_questions import provider_rotation
from app.services.ml_questions.llm_provider import OpenAICompatProvider
from app.tickets.api.deps import get_triage_provider

RETIRED_MODEL_IDS = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b:free",
}


def test_rotation_defaults_name_live_models() -> None:
    specs = provider_rotation._known_provider_specs()

    assert specs["groq"].default_model == "openai/gpt-oss-120b"
    assert specs["cerebras"].default_model == "gpt-oss-120b"
    assert specs["openrouter"].default_model == "openrouter/free"
    assert not {spec.default_model for spec in specs.values()} & RETIRED_MODEL_IDS


def test_provider_without_explicit_model_uses_a_live_groq_model() -> None:
    provider = OpenAICompatProvider(name="groq", api_key="k", base_url="http://x")

    assert provider.model == "openai/gpt-oss-120b"


def test_ticket_triage_uses_a_live_groq_model() -> None:
    assert get_triage_provider().model == "openai/gpt-oss-120b"
