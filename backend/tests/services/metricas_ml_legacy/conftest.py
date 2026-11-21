"""This world has only the legacy ML metrics tables: the costo SI follow-up registry holds only this area's callback,
so `despues.despachar` never reaches another area's tables (each area tests its callback in its own world; the
package's real loading is tested in `tests/services/costo_si/test_despues_postgres.py`)."""

from typing import Iterator

import pytest

from app.services.costo_si import despues
from app.services.costo_si.despues import metricas_ml_legacy


@pytest.fixture(autouse=True)
def _solo_metricas_ml_legacy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {"metricas_ml_legacy": metricas_ml_legacy.recostear})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
