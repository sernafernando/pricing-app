"""
ORM model for `ml_bot_answer_examples` — few-shot tone-grounding corpus (R-1101).

Seeded with the minimum MVP examples from the spec's Section 11 table (see
migration `alembic/versions/20260706_ml_bot_questions.py`). Included in every
drafting prompt as tone-grounding context (design §6 stage 3).
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class MlBotAnswerExample(Base):
    """A single buyer-question / bot-answer few-shot pair used for tone grounding."""

    __tablename__ = "ml_bot_answer_examples"

    id = Column(Integer, primary_key=True, index=True)
    question_example = Column(Text, nullable=False)
    answer_example = Column(Text, nullable=False)
    category = Column(String(40), nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    orden = Column(Integer, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<MlBotAnswerExample(id={self.id}, category={self.category})>"
