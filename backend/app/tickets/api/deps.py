"""Shared FastAPI dependencies for the tickets API.

`get_triage_provider` is a deliberate test seam (design §6 "Testability is
the design"): tests override it via `app.dependency_overrides` with a fake
provider, so the CI suite never needs a real `GROQ_TICKETS_KEY` or makes a
network call.
"""

from app.core.config import settings
from app.services.ml_questions.llm_provider import OpenAICompatProvider

_TRIAGE_MODEL = "llama-3.3-70b-versatile"


def get_triage_provider() -> OpenAICompatProvider:
    """Build the Groq provider used for ticket triage.

    Its own key (`GROQ_TICKETS_KEY`), not the ml-bot's roster — no
    `RotatingProvider`, no roster config row, so the shared-roster trap
    (obs #1299: `ROSTER_CONFIG_KEY` is a module constant shared by every
    caller) cannot occur here by construction. Reuses `GROQ_BASE_URL`
    (same vendor) and `OpenAICompatProvider.complete()` only — never the
    ml-bot's closed-schema parser (see `triage_service.py` module docstring).
    """
    return OpenAICompatProvider(
        name="groq-tickets",
        api_key=settings.GROQ_TICKETS_KEY,
        base_url=settings.GROQ_BASE_URL,
        model=_TRIAGE_MODEL,
    )
