"""Costo SI engine tests run without the other areas' post-recompute callbacks.

`queue.drenar` calls `despues.despachar`, which imports every module of `app.services.costo_si.despues` and runs the
callbacks they register (ML sale costs, legacy metrics, ventas por fuera...). Those callbacks read and write their own
tables, which the engine's throwaway world (`_world.py`) does not have: the first area callback would make every drain
test here fail. Each area tests its callback in its own world; the registry's own behaviour is tested in
`test_despues_postgres.py`, which registers probes on this empty registry. The test of the package loading there
turns real loading back on (it re-imports every module of the package) and registers the areas' callbacks as no-ops,
since they need tables this world does not have. Interface: handoffs/sell-in-costo-si-interfaz.md §3.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from app.services.costo_si import despues


@pytest.fixture(autouse=True)
def _sin_callbacks_de_otras_areas(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)  # do not import the area modules
    yield
