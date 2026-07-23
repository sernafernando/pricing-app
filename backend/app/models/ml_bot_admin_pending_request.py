"""
ORM model for `ml_bot_admin_pending_requests` — ML Bot Phase B, derive-to-admin
lane (sdd/ml-bot-admin-pending, migration `20260723_ml_bot_admin_pending`).

Dedicated back-office task lane, orthogonal to Phase A's `ml_bot_messages`
reply lifecycle (design "Architecture Decisions" #1): reply state and task
state are independent, mirroring the `bot_status`-vs-`status` split already
used there. A row is created (best-effort) when `drafting_service._draft_one`
classifies a settled anchor as `invoice_cuit_change` (`source='bot_derived'`),
or manually by an operator (`source='manual'`).

`status` state machine (CAS, mirrors `MlBotMessage.bot_status`):
    new -> in_progress -> {done|cancelled}
    in_progress -> new                       (release)

`done` is a fiscal audit-trail transition (design decision #5): it REQUIRES a
non-empty `resolved_cuit` and stamps `resolved_cuit`/`resolved_cuit_valid`/
`resolved_by`/`resolved_at` in the same CAS update — the invoiced CUIT may
differ from what the buyer originally asked for, so this is never a bare
status flip (PR2 enforces this at the endpoint; the column shape here is the
audit surface).

`superseded_values` (design decision #4): append-only JSON array of
`{cuit, name, at, source}` entries — recorded when a NEW different CUIT
supersedes the currently open row's extracted value, instead of silently
overwriting it.

Single-open-row invariant (design decision #8): enforced at the app level in
`admin_pending_service` (find-open-then-update) as the PRIMARY guarantee; a
Postgres-ONLY partial UNIQUE index on (pack_id, request_type) where
status IN ('new','in_progress') is a belt — guarded so sqlite CI (where a
`postgresql_where` partial index silently degrades to a FULL unique index)
never gets a stricter constraint than the real deployment target.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MlBotAdminPendingRequest(Base):
    """A single back-office task derived from (or manually created alongside)
    a postventa message, tracking a buyer-requested change (currently only
    `invoice_cuit_change`) through to human resolution."""

    __tablename__ = "ml_bot_admin_pending_requests"

    id = Column(BigInteger, primary_key=True)

    # Origin — nullable for manual rows (design "manual creation").
    message_id = Column(BigInteger, ForeignKey("ml_bot_messages.id"), nullable=True)
    pack_id = Column(String(32), nullable=True)
    buyer_id = Column(BigInteger, nullable=True)

    request_type = Column(
        String(40), nullable=False, default="invoice_cuit_change", server_default="invoice_cuit_change"
    )
    source = Column(String(16), nullable=False, default="bot_derived", server_default="bot_derived")

    raw_text = Column(Text, nullable=True)

    # LLM-extracted values — untrusted buyer text, never auto-applied without
    # human confirmation (design "PII / Threat").
    extracted_cuit = Column(String(20), nullable=True)
    extracted_name = Column(String(255), nullable=True)
    cuit_valid = Column(Boolean, nullable=True)

    # Pre-fill from `tb_mercadolibre_users_data` (best-effort, mirrors
    # `_enrich_message_nicknames`'s join by buyer_id -> mluser_id).
    prefill_nickname = Column(String(255), nullable=True)
    prefill_identification_type = Column(String(255), nullable=True)
    prefill_identification_number = Column(String(255), nullable=True)
    prefill_billing_doc_type = Column(String(255), nullable=True)
    prefill_billing_doc_number = Column(String(255), nullable=True)
    prefill_billing_first_name = Column(String(255), nullable=True)
    prefill_billing_last_name = Column(String(255), nullable=True)

    # Soft cross-check only (never auto-fixed): CUIT core vs stored DNI.
    doc_mismatch = Column(Boolean, nullable=False, default=False, server_default="false")

    # Best-effort AFIP enrichment (design decision #6) — never blocks/fails
    # row creation. `afip_status` in {"enriched","not_found","unavailable","skipped"}.
    afip_status = Column(String(16), nullable=True)
    afip_razon_social = Column(String(255), nullable=True)
    afip_condicion_iva = Column(String(64), nullable=True)
    afip_domicilio = Column(String(500), nullable=True)
    afip_checked_at = Column(DateTime(timezone=True), nullable=True)

    # Append-only trace of prior extracted values superseded by a later,
    # different extraction in the same open row.
    superseded_values = Column(JSON, nullable=True)

    status = Column(String(16), nullable=False, default="new", server_default="new")
    notes = Column(Text, nullable=True)
    cancel_reason = Column(Text, nullable=True)

    # Fiscal audit stamp — populated ONLY on the `done` transition.
    resolved_cuit = Column(String(20), nullable=True)
    resolved_cuit_valid = Column(Boolean, nullable=True)
    resolved_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    claimed_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_ml_bot_admin_pending_status", "status"),
        Index("idx_ml_bot_admin_pending_pack_id", "pack_id"),
        Index("idx_ml_bot_admin_pending_message_id", "message_id"),
        Index("idx_ml_bot_admin_pending_pack_request_type", "pack_id", "request_type"),
    )

    def __repr__(self) -> str:
        return f"<MlBotAdminPendingRequest(id={self.id}, pack_id={self.pack_id!r}, status={self.status})>"
