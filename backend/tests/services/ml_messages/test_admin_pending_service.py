"""
ML Bot Phase B (sdd/ml-bot-admin-pending), PR1 Phase 3 — unit tests for
`services/ml_messages/admin_pending_service.py`.

Mirrors `tests/unit/test_ml_bot_messages_drafting_service.py`'s SAVEPOINT-
based `_ctx` stub + `AsyncMock` conventions.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.models.ml_bot_admin_pending_request import MlBotAdminPendingRequest
from app.models.mercadolibre_user_data import MercadoLibreUserData
from app.services.afip_service import AfipServiceError
from app.services.ml_messages import admin_pending_service


class _ctx:
    """Mirrors `test_ml_bot_messages_drafting_service.py`'s `_ctx` stub."""

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


def _patched(db):
    return patch.object(admin_pending_service, "get_background_db", return_value=_ctx(db))


class TestDeriveCreatesOneRow:
    def test_happy_path_prefills_from_ml_user_data(self, db) -> None:
        db.add(
            MercadoLibreUserData(
                mluser_id=999,
                nickname="COMPRADOR999",
                identification_type="DNI",
                identification_number="14768351",
                billing_doc_type="CUIT",
                billing_doc_number="20147683511",
                billing_first_name="Juan",
                billing_last_name="Perez",
            )
        )
        db.flush()

        with (
            _patched(db),
            patch.object(admin_pending_service, "_enrich_afip", new=AsyncMock(return_value=("skipped", {}))),
        ):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p1",
                    buyer_id=999,
                    raw_text="mi cuit es 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name="Juan Perez",
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.pack_id == "p1"
        assert row.buyer_id == 999
        assert row.source == "bot_derived"
        assert row.status == "new"
        assert row.extracted_cuit == "20-14768351-1"
        assert row.extracted_name == "Juan Perez"
        assert row.prefill_nickname == "COMPRADOR999"
        assert row.prefill_billing_doc_number == "20147683511"


class TestDeriveInvalidCuitNeverAutocorrected:
    def test_invalid_cuit_stored_as_is_with_valid_false(self, db) -> None:
        with (
            _patched(db),
            patch.object(admin_pending_service, "_enrich_afip", new=AsyncMock(return_value=("skipped", {}))),
        ):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p2",
                    buyer_id=1000,
                    raw_text="cuit 20111111111",
                    extracted_cuit="20111111111",
                    extracted_name=None,
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.extracted_cuit == "20111111111"
        assert row.cuit_valid is False


class TestDeriveAfipDownStillCreatesRow:
    def test_afip_raises_row_still_created_with_unavailable_status(self, db) -> None:
        async def _raise(*args, **kwargs):
            raise AfipServiceError("no configurado")

        with _patched(db), patch.object(admin_pending_service, "get_persona", new=AsyncMock(side_effect=_raise)):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p3",
                    buyer_id=1001,
                    raw_text="cuit 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name="Juan Perez",
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.afip_status == "unavailable"

    def test_afip_timeout_still_creates_row(self, db) -> None:
        async def _hang(*args, **kwargs):
            await asyncio.sleep(10)

        with (
            _patched(db),
            patch.object(admin_pending_service, "get_persona", new=_hang),
            patch.object(admin_pending_service, "_AFIP_TIMEOUT_SECONDS", 0.01),
        ):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p4",
                    buyer_id=1002,
                    raw_text="cuit 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name=None,
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.afip_status == "unavailable"


class TestDeriveDuplicateCuitUpdatesAndSupersedes:
    def test_second_different_cuit_updates_open_row_and_supersedes(self, db) -> None:
        with (
            _patched(db),
            patch.object(admin_pending_service, "_enrich_afip", new=AsyncMock(return_value=("skipped", {}))),
        ):
            first_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p5",
                    buyer_id=1003,
                    raw_text="cuit 20-11111111-2",
                    extracted_cuit="20-11111111-2",
                    extracted_name="Old Name",
                )
            )
            second_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p5",
                    buyer_id=1003,
                    raw_text="mejor poné 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name="New Name",
                )
            )

        assert second_id == first_id
        rows = db.query(MlBotAdminPendingRequest).filter_by(pack_id="p5").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.extracted_cuit == "20-14768351-1"
        assert row.extracted_name == "New Name"
        assert row.superseded_values
        assert row.superseded_values[0]["cuit"] == "20-11111111-2"
        assert row.superseded_values[0]["name"] == "Old Name"


class TestDeriveDocMismatchFlag:
    def test_cuit_core_mismatched_with_stored_dni_sets_flag(self, db) -> None:
        db.add(
            MercadoLibreUserData(
                mluser_id=1004,
                nickname="COMPRADOR1004",
                identification_type="DNI",
                identification_number="99999999",
            )
        )
        db.flush()

        with (
            _patched(db),
            patch.object(admin_pending_service, "_enrich_afip", new=AsyncMock(return_value=("skipped", {}))),
        ):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p6",
                    buyer_id=1004,
                    raw_text="cuit 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name=None,
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.doc_mismatch is True

    def test_cuit_core_matches_stored_dni_no_mismatch(self, db) -> None:
        db.add(
            MercadoLibreUserData(
                mluser_id=1005,
                nickname="COMPRADOR1005",
                identification_type="DNI",
                identification_number="14768351",
            )
        )
        db.flush()

        with (
            _patched(db),
            patch.object(admin_pending_service, "_enrich_afip", new=AsyncMock(return_value=("skipped", {}))),
        ):
            row_id = asyncio.run(
                admin_pending_service.derive_from_message(
                    message_id=None,
                    pack_id="p7",
                    buyer_id=1005,
                    raw_text="cuit 20-14768351-1",
                    extracted_cuit="20-14768351-1",
                    extracted_name=None,
                )
            )

        row = db.query(MlBotAdminPendingRequest).filter_by(id=row_id).first()
        assert row is not None
        assert row.doc_mismatch is False
