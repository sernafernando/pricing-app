"""Contract of the REAL `get_background_db()` that test fakes of it rely on
(e.g. `bg_db` in `test_ml_write_log_promotions.py`): a normal exit commits,
an exception rolls back and re-raises, and the session is always closed."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core import database


@pytest.fixture()
def spy_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock(name="session")
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    return session


def test_normal_exit_commits_and_closes(spy_session: MagicMock) -> None:
    with database.get_background_db() as db:
        assert db is spy_session

    spy_session.commit.assert_called_once_with()
    spy_session.rollback.assert_not_called()
    spy_session.close.assert_called_once_with()


def test_exception_rolls_back_and_reraises(spy_session: MagicMock) -> None:
    with pytest.raises(ValueError, match="boom"):
        with database.get_background_db():
            raise ValueError("boom")

    spy_session.commit.assert_not_called()
    spy_session.rollback.assert_called_once_with()
    spy_session.close.assert_called_once_with()
