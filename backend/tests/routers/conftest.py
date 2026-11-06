"""Shared fixtures for router tests (also re-exported by `tests/workers/handlers/conftest.py`)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, create_engine, text

from app.models.combo_componente import ComboComponente
from app.services import rrhh_horas_extras_diario as diario
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable


class HeDetectionLock:
    """Plays "another process" against the HE detection advisory lock, on its own connections."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def held(self) -> Iterator[None]:
        """Hold the lock from another connection, inside an open transaction."""
        with self.engine.connect() as conn, conn.begin():
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": diario.DETECTION_LOCK_KEY})
            yield

    def is_held(self) -> bool:
        """Whether some other session holds the lock (a successful probe is released at once)."""
        with self.engine.connect() as conn:
            trans = conn.begin()
            acquired = conn.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": diario.DETECTION_LOCK_KEY}
            ).scalar()
            trans.rollback()
        return not acquired


@pytest.fixture()
def he_lock() -> Iterator[HeDetectionLock]:
    """The HE detection advisory lock, probed and held from separate Postgres connections."""
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    try:
        yield HeDetectionLock(engine)
    finally:
        engine.dispose()


# One combo no test sells, out of the range of the tests' product ids.
COMBO_SEMILLA, COMPONENTE_SEMILLA = 999_999_001, 999_999_002


@pytest.fixture(autouse=True)
def _bom_sincronizado(request) -> None:
    """The combo bill of materials starts synced for every test that uses `db`: sell in and sell out refuse an empty
    one (`CombosNoSincronizados`, 503 through the API), like ML costing. A test of that refusal deletes the row."""
    if "db" not in request.fixturenames:
        return
    db = request.getfixturevalue("db")
    db.add(ComboComponente(combo_item_id=COMBO_SEMILLA, componente_item_id=COMPONENTE_SEMILLA, cantidad=1))
    db.commit()
