"""
Phase A (PR1), T1.3 — ORM model test for the new `ml_bot_messages` bot
draft/classify columns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ml_bot_message import MlBotMessage


class TestMlBotMessageBotColumns:
    def test_defaults_on_insert(self, db) -> None:
        row = MlBotMessage(
            ml_message_id="msg-1",
            pack_id="1234567890123456",
            buyer_id=999,
            seller_id=413658225,
            text="hola",
            status="available",
            received_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotMessage).filter_by(ml_message_id="msg-1").first()
        assert retrieved is not None
        assert retrieved.bot_status is None
        assert retrieved.drafted_answer is None
        assert retrieved.intent_category is None
        assert retrieved.confidence is None
        assert retrieved.answer_source is None
        assert retrieved.llm_provider is None
        assert retrieved.attempts == 0
        assert retrieved.last_error is None
        assert retrieved.drafted_at is None

    def test_can_set_bot_status_and_draft_fields(self, db) -> None:
        row = MlBotMessage(
            ml_message_id="msg-2",
            pack_id="1234567890123457",
            buyer_id=999,
            seller_id=413658225,
            text="factura a",
            status="available",
            received_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.add(row)
        db.flush()

        row.bot_status = "awaiting_human"
        row.drafted_answer = "Claro, te paso los datos de facturación."
        row.intent_category = "invoice_cuit_change"
        row.confidence = 0.87
        row.answer_source = "bot"
        row.llm_provider = "groq/llama-3.3-70b-versatile"
        db.flush()

        retrieved = db.query(MlBotMessage).filter_by(ml_message_id="msg-2").first()
        assert retrieved.bot_status == "awaiting_human"
        assert retrieved.intent_category == "invoice_cuit_change"
        assert float(retrieved.confidence) == 0.87
