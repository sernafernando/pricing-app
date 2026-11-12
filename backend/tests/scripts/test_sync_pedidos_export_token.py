"""`scripts/sync_pedidos_export.py` (cron): PRICING_API_TOKEN comes from the
environment or, when unset, from backend/.env."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_pedidos_export.py"


@pytest.fixture()
def script(monkeypatch):
    # setenv first so monkeypatch restores the original state, even after
    # load_dotenv writes the variable into os.environ.
    monkeypatch.setenv("PRICING_API_TOKEN", "placeholder")
    monkeypatch.delenv("PRICING_API_TOKEN")
    spec = importlib.util.spec_from_file_location("sync_pedidos_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sent_headers(script, monkeypatch):
    captured: dict = {}

    class Response:
        status_code = 200

        def json(self):
            return {"registros_obtenidos": 0}

    def fake_post(url, headers, timeout):
        captured.update(headers)
        return Response()

    monkeypatch.setattr(script.requests, "post", fake_post)
    return captured


def write_env(tmp_path: Path, token: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(f"PRICING_API_TOKEN={token}\n")
    return env_file


def test_reads_the_token_from_backend_env_when_unset(script, sent_headers, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(script, "BACKEND_ENV", write_env(tmp_path, "from-dotenv"))

    assert script.sync_pedidos() == 0
    assert sent_headers == {"Authorization": "Bearer from-dotenv"}


def test_environment_variable_wins_over_backend_env(script, sent_headers, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(script, "BACKEND_ENV", write_env(tmp_path, "from-dotenv"))
    monkeypatch.setenv("PRICING_API_TOKEN", "from-environment")

    assert script.sync_pedidos() == 0
    assert sent_headers == {"Authorization": "Bearer from-environment"}


def test_no_token_anywhere_sends_no_authorization(script, sent_headers, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(script, "BACKEND_ENV", tmp_path / "missing.env")

    assert script.sync_pedidos() == 0
    assert sent_headers == {}


def test_backend_env_path_is_next_to_the_scripts_dir_not_cwd(script) -> None:
    assert script.BACKEND_ENV == SCRIPT.parent.parent / ".env"
