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


def select_ack_template(*, cuit_valid: bool | None) -> str:
    """Valid CUIT -> proceed message. Invalid or unknown -> ask the buyer to
    confirm before anything is changed (never auto-fixed).

    Validity is decided by mod-11 alone. The old extra condition — the
    extracted CUIT's middle digits matching the buyer's stored DNI — was
    removed: a buyer asking to re-invoice to a different taxpayer (their
    company, their employer, a third party) is the PREMISE of an
    `invoice_cuit_change` request, not an anomaly. Worse, a company CUIT
    (30-/33-/34-) never carries a DNI in those digits, so the check fired on
    every single one and told those buyers their perfectly valid CUIT could
    not be validated.
    """
    return ACK_CLEAN if cuit_valid is True else ACK_CONFIRM
