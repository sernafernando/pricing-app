"""Tests written before tacticals approval (handoffs/tacticals-aprobacion-plan.md) load a tactical and check what it
applies right away. Since then a load starts `pendiente` and applies nothing until it is approved (S2), and a money
edit sends it back (S4). `aprobar_siempre` keeps those tests about what they prove: every create, edit and replace
through `app.services.tacticals` is approved by its own author right after (self-approval is allowed, L31), so they
read the approved tactical. The approval rules themselves are proven without it
(`tests/services/test_tacticals_aprobacion_postgres.py`)."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from app.services import tacticals as service


@pytest.fixture
def aprobar_siempre(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    originales = {nombre: getattr(service, nombre) for nombre in ("crear", "editar", "reemplazar")}

    def aprobado(original):
        def envuelta(db, tactical_id_o_data, *args: Any, **kwargs: Any):
            tactical = original(db, tactical_id_o_data, *args, **kwargs)
            if tactical is not None and tactical.estado == "pendiente":
                usuario_id = args[1] if original is not originales["crear"] else args[0]
                return service.aprobar(db, tactical.id, usuario_id)
            return tactical

        return envuelta

    for nombre, original in originales.items():
        monkeypatch.setattr(service, nombre, aprobado(original))
    yield


@pytest.fixture
def cargas_aprobadas(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The same for a bonus, a purchase or a campaign loaded on its own (S6): the API's create loads it already
    approved, as before approval existed. Its edits still follow S4 (a money edit sends it back to pending)."""
    from app.services.sell_in import bonos_crud, compras
    from app.services.sell_out import campanas

    for modulo, nombre in ((bonos_crud, "crear_bono"), (compras, "crear_compra"), (campanas, "crear_campana")):
        original = getattr(modulo, nombre)

        def aprobada(*args: Any, _original=original, **kwargs: Any):
            kwargs.pop("estado", None)
            return _original(*args, **kwargs)

        monkeypatch.setattr(modulo, nombre, aprobada)
    yield


@pytest.fixture
def ediciones_aprobadas(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The same for an engine's own edit of an approved row (a bulk edit, a split): it stays approved, as if the
    approver approved it again right after, so the tests read what the edit applies. The S4 rule itself is proven
    without it (`tests/services/sell_out/test_aprobacion_edicion_postgres.py`)."""
    from app.services.sell_in import aprobacion

    monkeypatch.setattr(aprobacion, "a_pendiente_si_cambia", lambda *args, **kwargs: False)
    yield
