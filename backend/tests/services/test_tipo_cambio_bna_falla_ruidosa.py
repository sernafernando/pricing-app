"""The BNA rate update fails loudly (usd-tipo-cambio).

The rate stayed at 1570 from 2026-11-06 because the prod venv lacked the HTML parser (`lxml`): every run returned
`{'status': 'error', 'message': "No module named 'lxml'"}`, the script exited 0 and nobody noticed for 12 days.
Now each failed fetch logs an ERROR, counts consecutive failures in `worker_job_state` (`tipo_cambio.bna`), and after
`FALLAS_PARA_ALERTAR` in a row the owner gets ONE WhatsApp (the existing wabot channel); a success resets the count.
The cron script exits 1 on a failed fetch. The parser is a declared dependency (`requirements.txt`).
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from types import SimpleNamespace
from typing import Any, List

import pytest
from sqlalchemy.orm import Session

from app.models.tipo_cambio import TipoCambio
from app.models.worker_job_state import WorkerJobState
from app.services import tipo_cambio_service, wabot_client

BILLETES_HTML = (
    b"<html><body><table><tr><td>Dolar U.S.A</td><td>1530,00</td><td>1580,00</td></tr>"
    b"<tr><td>Euro</td><td>1700,00</td><td>1800,00</td></tr></table></body></html>"
)


@pytest.fixture
def alertas(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    enviadas: List[str] = []

    def _send(message: str) -> str:
        enviadas.append(message)
        return "sent"

    monkeypatch.setattr(wabot_client, "send_to_owner", _send)
    return enviadas


@pytest.fixture
def sin_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prod venv of 2026-11-06: importing the parser fails."""
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.html", None)


@pytest.fixture
def bna_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tipo_cambio_service.requests, "post", lambda *a, **k: SimpleNamespace(content=BILLETES_HTML, status_code=200)
    )
    monkeypatch.setattr(tipo_cambio_service.sell_out_queue, "enqueue_por_bna", lambda db, hoy: None)
    monkeypatch.setattr(tipo_cambio_service.bonos_costo, "encolar_por_bna", lambda db, hoy: None)


def _estado(db: Session) -> dict[str, Any]:
    db.expire_all()
    row = db.query(WorkerJobState).filter(WorkerJobState.name == tipo_cambio_service.ESTADO_JOB).first()
    assert row is not None
    return row.detail


def test_parser_is_an_installed_dependency() -> None:
    from lxml import html  # noqa: F401 -- fails when requirements.txt does not declare it


def test_missing_parser_returns_error_logs_error_and_counts_a_failure(
    db: Session, sin_parser: None, alertas: List[str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger=tipo_cambio_service.logger.name):
        resultado = tipo_cambio_service.actualizar_tipo_cambio_bna(db)

    assert resultado["status"] == "error"
    assert "lxml" in resultado["message"]
    errores = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errores and "lxml" in errores[0].getMessage()
    assert _estado(db)["fallas_consecutivas"] == 1
    assert db.query(TipoCambio).count() == 0
    assert alertas == []


def test_owner_is_alerted_once_after_consecutive_failures(db: Session, sin_parser: None, alertas: List[str]) -> None:
    for _ in range(tipo_cambio_service.FALLAS_PARA_ALERTAR - 1):
        tipo_cambio_service.actualizar_tipo_cambio_bna(db)
    assert alertas == []

    tipo_cambio_service.actualizar_tipo_cambio_bna(db)
    assert len(alertas) == 1
    assert "tipo de cambio" in alertas[0].lower()
    assert "lxml" in alertas[0]

    tipo_cambio_service.actualizar_tipo_cambio_bna(db)
    assert len(alertas) == 1
    estado = _estado(db)
    assert estado["fallas_consecutivas"] == tipo_cambio_service.FALLAS_PARA_ALERTAR + 1
    assert estado["alertado"] is True


def test_alert_wabot_did_not_take_is_retried_on_the_next_failure(
    db: Session, sin_parser: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    respuestas = iter(["failed: http 500", "sent"])
    enviadas: List[str] = []

    def _send(message: str) -> str:
        enviadas.append(message)
        return next(respuestas)

    monkeypatch.setattr(wabot_client, "send_to_owner", _send)
    for _ in range(tipo_cambio_service.FALLAS_PARA_ALERTAR + 2):
        tipo_cambio_service.actualizar_tipo_cambio_bna(db)

    assert len(enviadas) == 2
    assert _estado(db)["alertado"] is True


def test_success_stores_the_rate_and_resets_the_failures(
    db: Session, alertas: List[str], bna_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "lxml", None)
        m.setitem(sys.modules, "lxml.html", None)
        for _ in range(tipo_cambio_service.FALLAS_PARA_ALERTAR):
            tipo_cambio_service.actualizar_tipo_cambio_bna(db)
    assert len(alertas) == 1

    resultado = tipo_cambio_service.actualizar_tipo_cambio_bna(db)

    assert resultado == {"status": "success", "compra": 1530.0, "venta": 1580.0, "fuente": "BNA"}
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == date.today()).one()
    assert (tc.compra, tc.venta) == (1530.0, 1580.0)
    estado = _estado(db)
    assert estado["fallas_consecutivas"] == 0
    assert estado["alertado"] is False
    assert len(alertas) == 1


def test_script_exits_1_when_the_fetch_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from app.scripts import sync_tipo_cambio

    monkeypatch.setattr(sync_tipo_cambio, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        sync_tipo_cambio,
        "actualizar_tipo_cambio_bna",
        lambda db: {"status": "error", "message": "No module named 'lxml'"},
    )

    with pytest.raises(SystemExit) as salida:
        sync_tipo_cambio.main()

    assert salida.value.code == 1
    assert "No module named 'lxml'" in capsys.readouterr().out


def test_script_exits_0_when_the_fetch_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from app.scripts import sync_tipo_cambio

    monkeypatch.setattr(sync_tipo_cambio, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        sync_tipo_cambio,
        "actualizar_tipo_cambio_bna",
        lambda db: {"status": "success", "compra": 1530.0, "venta": 1580.0, "fuente": "BNA"},
    )

    sync_tipo_cambio.main()

    assert "1580.0" in capsys.readouterr().out
