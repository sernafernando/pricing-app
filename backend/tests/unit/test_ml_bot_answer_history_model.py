"""
Unit tests — `MlBotAnswerHistory` ORM model (ml-bot-dynamic-fewshot PR1).

Verifies table name, column types (esp. `Vector(384)` via
`pgvector.sqlalchemy.Vector`), defaults (`active=True`), and NOT NULL on
`embedding`. Runs on the shared SQLite `db` fixture — the `Vector` PG type is
remapped to a SQLite-compatible JSON column for tests (conftest.py), matching
the existing JSONB/UUID remapping pattern.
"""

from __future__ import annotations

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.exc import IntegrityError

from app.models.ml_bot_answer_history import EMBEDDING_DIM, MlBotAnswerHistory


class TestMlBotAnswerHistoryModel:
    def test_tablename(self) -> None:
        assert MlBotAnswerHistory.__tablename__ == "ml_bot_answer_history"

    def test_embedding_column_is_vector_384(self) -> None:
        column = MlBotAnswerHistory.__table__.c.embedding
        # `tests/conftest.py`'s `_patch_pg_types_for_sqlite` remaps PG-only
        # column types in-place on the shared `Base.metadata` the first time
        # the session-scoped `engine` fixture is built, so this column's type
        # object may already be the SQLite-compatible JSON remap (not the
        # original `Vector`) depending on test execution order across the
        # whole suite — tolerate either, but require `Vector(384)` when it
        # HASN'T been remapped yet, so the assertion still catches a wrong
        # dimension/type in the actual model declaration.
        if isinstance(column.type, Vector):
            assert column.type.dim == EMBEDDING_DIM
        else:
            assert isinstance(column.type, JSON)
        assert column.nullable is False

    def test_insert_and_read_round_trip_with_defaults(self, db) -> None:
        row = MlBotAnswerHistory(
            question_text="¿Tienen stock del modelo azul?",
            answer_text="¡Hola! Sí, tenemos stock disponible de ese modelo.",
            item_id="MLA123456789",
            edited_flag=False,
            category="stock",
            embedding=[0.1] * 384,
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotAnswerHistory).filter_by(item_id="MLA123456789").first()
        assert retrieved is not None
        assert retrieved.active is True
        assert retrieved.category == "stock"
        assert retrieved.edited_flag is False
        assert len(retrieved.embedding) == 384

    def test_embedding_not_nullable(self, db) -> None:
        row = MlBotAnswerHistory(
            question_text="¿Es compatible?",
            answer_text="Sí, es compatible.",
            item_id="MLA1",
            edited_flag=True,
            embedding=None,
        )
        db.add(row)
        with pytest.raises(IntegrityError):
            db.flush()
