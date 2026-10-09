"""The billing runbook section names the handler, the flag and the worker unit that exist."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.workers.handlers import ml_billing

DOC = Path(__file__).resolve().parents[3] / "docs" / "RUNBOOKS.md"


@pytest.fixture(scope="module")
def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### ML billing sweep (`ml_billing.sweep`)")
    return text[start : text.index("\n### ", start + 1)]


def test_the_section_names_the_handler_flag_and_the_deploy_steps(section) -> None:
    assert ml_billing.BILLING_HANDLER in section
    assert hasattr(settings, "ML_BILLING_ENABLED") and "ML_BILLING_ENABLED" in section
    assert "crontab -e" in section and "sudo systemctl restart pricing-worker-ml" in section
