"""catalog_competition_refresh handler: drain queue via refrescar_competencia_catalogo."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers.catalog_competition_refresh import CatalogCompetitionRefreshHandler

pytestmark = pytest.mark.postgres


def now() -> datetime:
    return datetime.now(timezone.utc)


def ctx() -> WorkerContext:
    return WorkerContext(deadline=now() + timedelta(seconds=30), worker_name="test")


@pytest.fixture
def env(mlpub_pg):
    CatalogCompetitionRefreshPending.__table__.create(bind=mlpub_pg, checkfirst=True)
    return mlpub_pg


def session_factory(engine):
    Session = sessionmaker(bind=engine)

    @contextmanager
    def factory():
        db = Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return factory


def put(engine, mla: str, *, due_in: float = -1, attempts: int = 0) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO catalog_competition_refresh_pending (mla, due_at, attempts) "
                "VALUES (:m, :d, :a)"
            ),
            {"m": mla, "d": now() + timedelta(seconds=due_in), "a": attempts},
        )


def pending_mlas(engine) -> set[str]:
    with engine.connect() as conn:
        return {r.mla for r in conn.execute(text("SELECT mla FROM catalog_competition_refresh_pending"))}


class TestRegistration:
    def test_in_ml_registry(self) -> None:
        assert "ml_publications.catalog_competition_refresh" in [h.name for h in registry.ML_PUBLICATIONS_REGISTRY]


class TestDrain:
    def test_due_row_refreshed_and_dropped(self, env) -> None:
        put(env, "MLA1")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env))
        with mock.patch(
            "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
            new=mock.AsyncMock(return_value=[]),
        ) as refresh:
            result = handler.run(ctx())
        assert result.detail["refreshed"] == 1
        assert refresh.await_count == 1
        assert pending_mlas(env) == set()

    def test_failed_refresh_reschedules(self, env) -> None:
        put(env, "MLA2")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env))
        with mock.patch(
            "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
            new=mock.AsyncMock(side_effect=RuntimeError("proxy down")),
        ):
            result = handler.run(ctx())
        assert result.detail["failed"] == 1
        assert "MLA2" in pending_mlas(env)
