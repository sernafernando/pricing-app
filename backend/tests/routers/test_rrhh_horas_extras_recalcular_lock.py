"""`POST /rrhh/horas-extras/recalcular` and the HE detection lock shared with the worker and the script.

Only a lock that is actually HELD blocks a recalculation: the lockfile stays on disk after every run,
so its mere existence must never answer 409. While the endpoint recalculates it holds the lock itself,
so the worker skips instead of overlapping."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
from app.routers import rrhh_horas_extras as router
from app.services import rrhh_horas_extras_diario as diario

RESULT = {"procesados": 1, "creados": 0, "actualizados": 0, "alertas": 0, "errores": 0, "pendientes_turno": 0}


@contextmanager
def held(path: Path) -> Iterator[None]:
    """Hold the lock from another open file description, as another process would."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        os.close(fd)


def is_held(path: Path) -> bool:
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


@pytest.fixture()
def lock_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "rrhh_he_cron.lock"
    monkeypatch.setattr(diario, "LOCK_PATHS", (path,))
    return path


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch, lock_path: Path) -> list[bool]:
    """Fake detection that records whether the lock was held while it ran."""
    held_during_run: list[bool] = []

    class FakeService:
        def __init__(self, db) -> None:
            pass

        def detectar_he_periodo(self, fecha_desde, fecha_hasta, empleado_ids=None):
            held_during_run.append(is_held(lock_path))
            return dict(RESULT)

    monkeypatch.setattr(router, "HorasExtrasService", FakeService)
    monkeypatch.setattr(router, "_check_permiso", lambda db, user, codigo: None)
    return held_during_run


def _recalcular(db):
    db.add(RRHHHorasExtrasConfig(id=1))
    db.flush()
    data = router.RecalcularRequest(fecha_desde=date(2026, 5, 5), fecha_hasta=date(2026, 5, 6))
    return router.recalcular_periodo(data, db=db, current_user=object())


def test_a_leftover_lockfile_that_nobody_holds_does_not_block(db, service, lock_path) -> None:
    lock_path.touch()  # left behind by an earlier run: the prod bug answered 409 forever

    assert _recalcular(db) == RESULT
    assert service == [True]


def test_a_missing_lockfile_does_not_block(db, service, lock_path) -> None:
    assert _recalcular(db) == RESULT


def test_a_held_lock_answers_409_without_recalculating(db, service, lock_path) -> None:
    with held(lock_path), pytest.raises(HTTPException) as exc:
        _recalcular(db)

    assert exc.value.status_code == 409
    assert service == []


def test_the_lock_is_released_after_the_recalculation(db, service, lock_path) -> None:
    _recalcular(db)

    assert is_held(lock_path) is False


def test_an_unusable_lock_directory_fails_clearly(db, service, monkeypatch, tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(diario, "LOCK_PATHS", (blocker / "rrhh_he_cron.lock",))

    with pytest.raises(HTTPException) as exc:
        _recalcular(db)

    assert exc.value.status_code == 503
    assert "lock" in exc.value.detail
    assert service == []
