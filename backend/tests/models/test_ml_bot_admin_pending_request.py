"""
ML Bot Phase B (sdd/ml-bot-admin-pending), PR1 Group 1 — ORM model test for
`ml_bot_admin_pending_requests` (design "Schema").
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ml_bot_admin_pending_request import MlBotAdminPendingRequest


class TestMlBotAdminPendingRequestDefaults:
    def test_defaults_on_insert(self, db) -> None:
        row = MlBotAdminPendingRequest(
            pack_id="1234567890123456",
            buyer_id=999,
            raw_text="quiero factura a con cuit 20-14768351-1",
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotAdminPendingRequest).filter_by(pack_id="1234567890123456").first()
        assert retrieved is not None
        assert retrieved.request_type == "invoice_cuit_change"
        assert retrieved.source == "bot_derived"
        assert retrieved.status == "new"
        assert retrieved.doc_mismatch is False
        assert retrieved.message_id is None
        assert retrieved.extracted_cuit is None
        assert retrieved.extracted_name is None
        assert retrieved.cuit_valid is None
        assert retrieved.afip_status is None
        assert retrieved.superseded_values is None
        assert retrieved.resolved_cuit is None
        assert retrieved.resolved_cuit_valid is None
        assert retrieved.resolved_by is None
        assert retrieved.resolved_at is None
        assert retrieved.created_at is not None

    def test_can_set_extracted_and_afip_fields(self, db) -> None:
        row = MlBotAdminPendingRequest(
            pack_id="1234567890123457",
            buyer_id=999,
            raw_text="mi cuit es 20-14768351-1",
            extracted_cuit="20147683511",
            extracted_name="Juan Perez",
            cuit_valid=True,
            afip_status="enriched",
            afip_razon_social="Perez Juan",
        )
        db.add(row)
        db.flush()

        retrieved = db.query(MlBotAdminPendingRequest).filter_by(pack_id="1234567890123457").first()
        assert retrieved.extracted_cuit == "20147683511"
        assert retrieved.extracted_name == "Juan Perez"
        assert retrieved.cuit_valid is True
        assert retrieved.afip_status == "enriched"
        assert retrieved.afip_razon_social == "Perez Juan"

    def test_can_append_superseded_values_and_resolve(self, db) -> None:
        row = MlBotAdminPendingRequest(
            pack_id="1234567890123458",
            buyer_id=999,
            raw_text="cuit nuevo 20-14768351-1",
        )
        db.add(row)
        db.flush()

        row.superseded_values = [{"cuit": "20111111112", "name": "Old Name", "at": "2026-07-01T00:00:00+00:00"}]
        row.status = "done"
        row.resolved_cuit = "20147683511"
        row.resolved_cuit_valid = True
        row.resolved_at = datetime.now(timezone.utc)
        db.flush()

        retrieved = db.query(MlBotAdminPendingRequest).filter_by(pack_id="1234567890123458").first()
        assert retrieved.superseded_values == [
            {"cuit": "20111111112", "name": "Old Name", "at": "2026-07-01T00:00:00+00:00"}
        ]
        assert retrieved.status == "done"
        assert retrieved.resolved_cuit == "20147683511"
        assert retrieved.resolved_cuit_valid is True
