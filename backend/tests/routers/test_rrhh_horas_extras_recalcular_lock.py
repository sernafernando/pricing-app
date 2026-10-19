"""`POST /rrhh/horas-extras/recalcular` and the HE detection lock shared with the worker and the script.

The lock is a Postgres transaction-scoped advisory lock (`pg_try_advisory_xact_lock`), taken in the
request's own session: every process sees it whatever its OS user or `/tmp`, and it is released exactly
when the recalculation's writes commit or roll back. Two connections: one holds the lock inside an open
transaction, the other must see it as held."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.routers import rrhh_horas_extras as router

pytestmark = pytest.mark.postgres

RESULT = {"procesados": 1, "creados": 0, "actualizados": 0, "alertas": 0, "errores": 0, "pendientes_turno": 0}


@pytest.fixture()
def pg(he_lock) -> Engine:
    return he_lock.engine


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch, he_lock) -> list[dict]:
    """Fake detection: records its arguments and whether the lock was held while it ran."""
    recorded: list[dict] = []

    class FakeService:
        def __init__(self, db) -> None:
            pass

        def detectar_he_periodo(self, fecha_desde, fecha_hasta, empleado_ids=None, commit=True):
            recorded.append({"commit": commit, "held": he_lock.is_held()})
            return dict(RESULT)

    monkeypatch.setattr(router, "HorasExtrasService", FakeService)
    monkeypatch.setattr(router, "_check_permiso", lambda db, user, codigo: None)
    monkeypatch.setattr(router, "_get_config_or_500", lambda db: SimpleNamespace(cap_dias_recalculo_manual=90))
    return recorded


def _recalcular(db: Session):
    data = router.RecalcularRequest(fecha_desde=date(2026, 5, 5), fecha_hasta=date(2026, 5, 6))
    return router.recalcular_periodo(data, db=db, current_user=object())


def test_it_recalculates_holding_the_lock_and_commits_before_releasing_it(pg, he_lock, calls) -> None:
    held_at_commit: list[bool] = []
    with Session(bind=pg) as db:
        real_commit = db.commit

        def spying_commit() -> None:
            held_at_commit.append(he_lock.is_held())
            real_commit()

        db.commit = spying_commit  # type: ignore[method-assign]
        assert _recalcular(db) == RESULT

        # the service does not commit on its own: the endpoint commits the writes while the lock is held
        assert calls == [{"commit": False, "held": True}]
        assert held_at_commit == [True]
        assert he_lock.is_held() is False


def test_a_lock_held_by_another_run_answers_409_without_recalculating(pg, he_lock, calls) -> None:
    with he_lock.held(), Session(bind=pg) as db, pytest.raises(HTTPException) as exc:
        _recalcular(db)

    assert exc.value.status_code == 409
    assert exc.value.detail == "Otra detección de horas extras está en curso. Intentá de nuevo en unos minutos."
    assert calls == []


def test_a_database_error_taking_the_lock_answers_503_without_leaking_it(pg, calls, monkeypatch, caplog) -> None:
    with Session(bind=pg) as db:

        def broken_execute(*args, **kwargs):
            raise OperationalError("SELECT pg_try_advisory_xact_lock", {}, Exception("connection lost"))

        monkeypatch.setattr(db, "execute", broken_execute)
        with pytest.raises(HTTPException) as exc:
            _recalcular(db)

    assert exc.value.status_code == 503
    # the client gets neutral copy; the database error only goes to the log
    assert (
        exc.value.detail
        == "No se pudo verificar si hay otra detección de horas extras en curso. Intentá de nuevo en unos minutos."
    )
    assert "connection lost" in caplog.text
    assert calls == []
