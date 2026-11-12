"""catalog_competition_refresh handler: drain queue via refrescar_competencia_catalogo."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.settings_store import set_setting
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
    set_setting("catalog_competition_refresh.enabled", True, "test")
    set_setting("catalog_competition_refresh.rate_per_min", 60, "test")
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
            text("INSERT INTO catalog_competition_refresh_pending (mla, due_at, attempts) VALUES (:m, :d, :a)"),
            {"m": mla, "d": now() + timedelta(seconds=due_in), "a": attempts},
        )


def pending_mlas(engine) -> set[str]:
    with engine.connect() as conn:
        return {r.mla for r in conn.execute(text("SELECT mla FROM catalog_competition_refresh_pending"))}


def _row(status: str) -> SimpleNamespace:
    return SimpleNamespace(fetch_status=status)


class TestRegistration:
    def test_in_ml_registry(self) -> None:
        assert "ml_publications.catalog_competition_refresh" in [h.name for h in registry.ML_PUBLICATIONS_REGISTRY]


class TestDrain:
    def test_due_row_refreshed_and_dropped(self, env) -> None:
        put(env, "MLA1")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env), pacer=Pacer(rate_per_sec=20))
        with (
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
                new=mock.AsyncMock(return_value=[_row("ok")]),
            ) as refresh,
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.is_active",
                return_value=True,
            ),
        ):
            result = handler.run(ctx())
        assert result.detail["refreshed"] == 1
        assert refresh.await_count == 1
        assert pending_mlas(env) == set()

    def test_error_fetch_status_reschedules(self, env) -> None:
        put(env, "MLA2")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env), pacer=Pacer(rate_per_sec=20))
        with (
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
                new=mock.AsyncMock(return_value=[_row("error")]),
            ),
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.is_active",
                return_value=True,
            ),
        ):
            result = handler.run(ctx())
        assert result.detail["failed"] == 1
        assert "MLA2" in pending_mlas(env)

    def test_not_catalog_is_dropped(self, env) -> None:
        put(env, "MLA3")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env), pacer=Pacer(rate_per_sec=20))
        with (
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
                new=mock.AsyncMock(return_value=[_row("not_catalog")]),
            ),
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.is_active",
                return_value=True,
            ),
        ):
            result = handler.run(ctx())
        assert result.detail["dropped"] == 1
        assert pending_mlas(env) == set()

    def test_inactive_mla_dropped_without_refresh(self, env) -> None:
        put(env, "MLA4")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env), pacer=Pacer(rate_per_sec=20))
        with (
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.refrescar_competencia_catalogo",
                new=mock.AsyncMock(return_value=[_row("ok")]),
            ) as refresh,
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.is_active",
                return_value=False,
            ),
        ):
            result = handler.run(ctx())
        assert result.detail["dropped"] == 1
        assert refresh.await_count == 0
        assert pending_mlas(env) == set()


class TestRealPersistence:
    """Regression: the real `refrescar_competencia_catalogo` persists ORM rows that the
    session commit expires; reading them after the session closes raised
    DetachedInstanceError, which settled as `error` and quarantined the MLA."""

    def test_status_read_from_persisted_row_settles(self, env) -> None:
        from app.models.ml_catalog_competition import MLCatalogCompetition

        MLCatalogCompetition.__table__.create(bind=env, checkfirst=True)
        put(env, "MLA5")
        handler = CatalogCompetitionRefreshHandler(session_factory=session_factory(env), pacer=Pacer(rate_per_sec=20))
        with (
            mock.patch(
                "app.services.ml_catalog_competition_service.ml_webhook_client.get_catalog_competition",
                new=mock.AsyncMock(return_value={"status": "not_catalog"}),
            ),
            mock.patch(
                "app.workers.handlers.catalog_competition_refresh.is_active",
                return_value=True,
            ),
        ):
            result = handler.run(ctx())
        assert result.detail["failed"] == 0
        assert result.detail["dropped"] == 1
        assert pending_mlas(env) == set()
        with env.connect() as conn:
            stored = conn.execute(
                text("SELECT fetch_status FROM ml_catalog_competition WHERE mla = 'MLA5'")
            ).scalar_one()
        assert stored == "not_catalog"
