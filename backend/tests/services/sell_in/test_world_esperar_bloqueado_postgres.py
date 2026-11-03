"""`si.esperar_bloqueado_por` sees a waiter whose backend starts after its first poll: pg_stat_activity is a snapshot
cached for the whole transaction, so each poll must run in a transaction of its own."""

from __future__ import annotations

import threading
from typing import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from tests.services.sell_in import _world as si

pytestmark = pytest.mark.postgres
K = 987654


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with si.world("esperar_bloqueado") as engine:
        yield engine


def _waiter(engine: Engine, fin: threading.Event) -> None:
    fresco = create_engine(engine.url, poolclass=NullPool)  # a new backend, like the save's connection
    with fresco.connect() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": K})
        c.rollback()
    fresco.dispose()
    fin.set()


@pytest.mark.parametrize("retraso", [0.0, 0.4])
def test_helper_sees_a_waiter_whose_backend_starts_after_its_first_poll(engine: Engine, retraso) -> None:
    fin = threading.Event()
    with engine.connect() as dueno:
        dueno.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": K})
        pid = dueno.execute(text("SELECT pg_backend_pid()")).scalar()
        hilo = threading.Timer(retraso, _waiter, (engine, fin))
        hilo.start()
        try:
            si.esperar_bloqueado_por(engine, pid)
        finally:
            dueno.rollback()  # never leaves the waiter behind
            hilo.join(30)
    assert fin.is_set()
