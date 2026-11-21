"""The engine tests' registry is empty and never imports the area modules (see conftest.py)."""

from __future__ import annotations

import importlib
from datetime import date

import pytest

from app.services.costo_si import despues


def test_engine_tests_dispatch_to_no_area_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_importar(nombre: str, *args, **kwargs):
        raise AssertionError(f"an engine test imported an area callback module: {nombre}")

    monkeypatch.setattr(importlib, "import_module", no_importar)

    despues.despachar(None, 1, date(2026, 10, 1))  # a callback would need a session: None proves none ran

    assert despues._CALLBACKS == {}
