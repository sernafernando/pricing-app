"""
Judgment Day fix: `poll_interval_seconds` is seeded/documented as the
panel-editable interval for the ml-bot ingest/draft background loops in
app/main.py, but was never actually read — both loops hardcoded
`asyncio.sleep(30)`. Covers `_resolve_ml_bot_poll_interval_seconds()`, the
helper both loops now call each tick.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.main import _resolve_ml_bot_poll_interval_seconds
from app.models.ml_bot_config import MlBotConfig


class _ctx:
    def __init__(self, db) -> None:
        self._db = db
        self._nested = None

    def __enter__(self):
        self._nested = self._db.begin_nested()
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._nested.commit()
        else:
            self._nested.rollback()
        return False


def _patch_db(db):
    return patch("app.core.database.get_background_db", return_value=_ctx(db))


class TestResolveMlBotPollIntervalSeconds:
    def test_uses_configured_value(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="45", tipo="int"))
        db.commit()

        with _patch_db(db):
            result = asyncio.run(_resolve_ml_bot_poll_interval_seconds())

        assert result == 45

    def test_falls_back_to_default_when_missing(self, db) -> None:
        db.commit()

        with _patch_db(db):
            result = asyncio.run(_resolve_ml_bot_poll_interval_seconds())

        assert result == 30

    def test_db_error_falls_back_to_default(self) -> None:
        with patch("app.core.database.get_background_db", side_effect=RuntimeError("db down")):
            result = asyncio.run(_resolve_ml_bot_poll_interval_seconds())

        assert result == 30
