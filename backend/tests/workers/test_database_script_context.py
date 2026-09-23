"""RED/GREEN -- `_is_script_context()` also matches the `/workers/` path
fragment (ventas-ml-rediseno PR2.T6, design D4 'DB sessions'): the worker
runs standalone under systemd (`python -m app.workers.run`), same NullPool
requirement as `/scripts/` and `alembic/env.py` -- it must never hold a
persistent pool.
"""

from __future__ import annotations

from app.core.database import _is_script_context


class _FakeMainModule:
    def __init__(self, file_path: str) -> None:
        self.__file__ = file_path


class TestIsScriptContextMatchesWorkersPath:
    def test_workers_run_module_is_treated_as_script_context(self, monkeypatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "__main__", _FakeMainModule("/app/backend/app/workers/run.py"))
        assert _is_script_context() is True

    def test_scripts_path_still_matches(self, monkeypatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "__main__", _FakeMainModule("/app/backend/app/scripts/foo.py"))
        assert _is_script_context() is True

    def test_ordinary_uvicorn_entrypoint_does_not_match(self, monkeypatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "__main__", _FakeMainModule("/app/backend/venv/bin/uvicorn"))
        assert _is_script_context() is False
