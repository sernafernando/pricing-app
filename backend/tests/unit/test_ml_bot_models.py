"""
T-A1: Unit tests — ml_bot_questions / ml_bot_config / ml_bot_answer_examples ORM models.

Verifies:
- Each model maps to its expected table name.
- Column defaults match design §3 (status='received', bot_enabled=false, etc).
- Unique constraint on ml_bot_questions.ml_question_id raises IntegrityError on dup.

SQLite-runnable via the shared `db` fixture (conftest.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_answer_example import MlBotAnswerExample


class TestMlBotQuestionModel:
    def test_tablename(self) -> None:
        assert MlBotQuestion.__tablename__ == "ml_bot_questions"

    def test_insert_and_read_round_trip_with_defaults(self, db) -> None:
        row = MlBotQuestion(
            ml_question_id=555001,
            item_id="MLA123456789",
            question_text="¿Tienen stock?",
            question_date=datetime(2026, 7, 6, 23, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotQuestion).filter_by(ml_question_id=555001).first()
        assert retrieved is not None
        # Design §2/§3 default state
        assert retrieved.status == "received"
        assert retrieved.injection_flag is False
        assert retrieved.fallback_used is False
        assert retrieved.attempts == 0
        assert retrieved.answer_source is None
        assert retrieved.drafted_answer is None

    def test_ml_question_id_unique_constraint(self, db) -> None:
        row1 = MlBotQuestion(
            ml_question_id=555002,
            item_id="MLA1",
            question_text="Pregunta 1",
            question_date=datetime(2026, 7, 6, 20, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row1)
        db.flush()

        row2 = MlBotQuestion(
            ml_question_id=555002,
            item_id="MLA1",
            question_text="Pregunta 2 duplicada",
            question_date=datetime(2026, 7, 6, 21, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row2)
        with pytest.raises(IntegrityError):
            db.flush()


class TestMlBotConfigModel:
    def test_tablename(self) -> None:
        assert MlBotConfig.__tablename__ == "ml_bot_config"

    def test_insert_and_read_round_trip(self, db) -> None:
        row = MlBotConfig(
            clave="bot_enabled",
            valor="false",
            descripcion="Habilita/deshabilita el bot globalmente",
            tipo="bool",
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotConfig).filter_by(clave="bot_enabled").first()
        assert retrieved is not None
        assert retrieved.valor == "false"
        assert retrieved.tipo == "bool"

    def test_clave_is_primary_key(self, db) -> None:
        row1 = MlBotConfig(clave="wait_minutes", valor="5", tipo="int")
        db.add(row1)
        db.flush()

        row2 = MlBotConfig(clave="wait_minutes", valor="10", tipo="int")
        db.add(row2)
        with pytest.raises(IntegrityError):
            db.flush()


class TestMlBotAnswerExampleModel:
    def test_tablename(self) -> None:
        assert MlBotAnswerExample.__tablename__ == "ml_bot_answer_examples"

    def test_insert_and_read_round_trip_with_defaults(self, db) -> None:
        row = MlBotAnswerExample(
            question_example="¿Tienen stock del modelo azul?",
            answer_example=(
                "¡Hola! Sí, tenemos stock disponible de ese modelo. "
                "Cualquier consulta, quedamos a disposición."
            ),
            category="stock",
        )
        db.add(row)
        db.flush()

        retrieved = (
            db.query(MlBotAnswerExample)
            .filter_by(question_example="¿Tienen stock del modelo azul?")
            .first()
        )
        assert retrieved is not None
        assert retrieved.active is True
        assert retrieved.orden == 0
