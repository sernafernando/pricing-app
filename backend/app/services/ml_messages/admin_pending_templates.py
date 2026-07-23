"""
Ack template selection for the ML Bot Phase B derive-to-admin lane (sdd/
ml-bot-admin-pending). BE computes `suggested_ack_template` from row flags
(design decision #7: single source of truth, no FE drift) — PR2's detail
endpoint calls `select_ack_template`; nothing here sends anything, the
operator always hand-picks/edits the final message via Phase A's existing
take-over -> edit -> `POST /messages/{id}/send` path.
"""

from __future__ import annotations

ACK_CLEAN = "¡Hola! Ya registramos tus datos de facturación, se realizará el cambio a la brevedad."

ACK_CONFIRM = (
    "¡Hola! Para poder actualizar tu factura necesitamos que nos confirmes tu CUIT completo "
    "(con guiones), ya que el que nos llegó no pudimos validarlo. ¡Gracias!"
)


def select_ack_template(*, cuit_valid: bool | None, doc_mismatch: bool) -> str:
    """Clean/valid CUIT, no mismatch -> proceed message. Invalid CUIT or a
    doc mismatch -> ask the buyer to confirm before anything is changed
    (never auto-fixed, design "PII / Threat")."""
    if cuit_valid is True and not doc_mismatch:
        return ACK_CLEAN
    return ACK_CONFIRM
