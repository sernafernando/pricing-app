"""The ERP sync's Compras hook refreshes `pedidos_compra.fecha_factura`.

`sync_commercial_transactions_guid` runs on every ERP sync; after the backward
matching commits, it calls `refrescar_fechas_factura` so a changed ct_date, an
annulment or a late-appearing invoice reaches the app-side column. Like the
rest of the hook it is best-effort: a failure there must not undo the matching
nor break the sync. The ERP call and the DB session are faked; the matching
functions are replaced on their module (the hook imports them at call time).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.scripts import sync_commercial_transactions_guid as sync_mod
from app.services import erp_matching_service

_RECORD = {"ct_transaction": "990001", "ct_guid": "6f1c2a3e-1b2c-4d5e-8f90-123456789abc"}


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict]:
        return [_RECORD]


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, *args, **kwargs) -> _FakeResponse:
        return _FakeResponse()


@pytest.fixture
def calls(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(sync_mod.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(erp_matching_service, "reconciliar_lineas_facturadas", lambda db: calls.append("lineas") or 0)
    monkeypatch.setattr(erp_matching_service, "validar_catalogo_populado", lambda db: None)
    monkeypatch.setattr(
        erp_matching_service,
        "match_backward",
        lambda db, cts_synced: (
            calls.append("match_backward") or {"pedidos_asociados": 0, "cts_procesadas": len(cts_synced), "errores": 0}
        ),
    )
    monkeypatch.setattr(
        erp_matching_service,
        "match_ncs_backward",
        lambda db, cts_synced: {"ncs_asociadas": 0, "errores": 0},
    )
    return calls


def _db(calls: list[str]) -> MagicMock:
    db = MagicMock()
    db.commit.side_effect = lambda: calls.append("commit")
    db.rollback.side_effect = lambda: calls.append("rollback")
    return db


def test_hook_refresca_fechas_despues_del_matching(calls, monkeypatch) -> None:
    monkeypatch.setattr(erp_matching_service, "refrescar_fechas_factura", lambda db: calls.append("refrescar") or 0)

    resultado = asyncio.run(sync_mod.sync_commercial_transactions_guid(_db(calls)))

    assert "error" not in resultado
    assert calls.index("match_backward") < calls.index("refrescar")
    assert calls[-1] == "commit"


def test_falla_del_refresco_no_deshace_el_matching_ni_el_sync(calls, monkeypatch) -> None:
    def _boom(db):
        calls.append("refrescar")
        raise RuntimeError("view unavailable")

    monkeypatch.setattr(erp_matching_service, "refrescar_fechas_factura", _boom)

    resultado = asyncio.run(sync_mod.sync_commercial_transactions_guid(_db(calls)))

    assert resultado == {"nuevos": 1, "actualizados": 0, "errores": 0}
    # The matching committed before the refresh ran; only the refresh rolls back.
    assert calls[calls.index("match_backward") :] == [
        "match_backward",
        "commit",
        "refrescar",
        "rollback",
        "lineas",
        "commit",
    ]


def test_hook_reconcilia_lineas_facturadas_despues_de_las_fechas(calls, monkeypatch) -> None:
    monkeypatch.setattr(erp_matching_service, "refrescar_fechas_factura", lambda db: calls.append("refrescar") or 0)

    asyncio.run(sync_mod.sync_commercial_transactions_guid(_db(calls)))

    assert calls[calls.index("refrescar") :] == ["refrescar", "commit", "lineas", "commit"]


def test_falla_de_las_lineas_no_deshace_las_fechas(calls, monkeypatch) -> None:
    def _boom(db):
        calls.append("lineas")
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr(erp_matching_service, "refrescar_fechas_factura", lambda db: calls.append("refrescar") or 0)
    monkeypatch.setattr(erp_matching_service, "reconciliar_lineas_facturadas", _boom)

    resultado = asyncio.run(sync_mod.sync_commercial_transactions_guid(_db(calls)))

    assert resultado == {"nuevos": 1, "actualizados": 0, "errores": 0}
    assert calls[calls.index("refrescar") :] == ["refrescar", "commit", "lineas", "rollback"]
