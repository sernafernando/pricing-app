from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TnReconcileExcepcion(Base):
    """An anomaly an operator reviewed and judged INTENTIONAL.

    Distinct from `TnReconcileBanlist`, and deliberately so. Banning means
    "we don't want to publish this" and only hides the publish candidates;
    it never hides a data-quality anomaly, because banning must not be a
    way to sweep a broken publication out of review. That rule is right,
    but it left the anomaly verdicts with no exit at all: a legitimately
    different SKU, or a deliberate duplicate, screamed forever. An alert
    that cannot be silenced is one people learn to ignore entirely —
    including the day it is real.

    Keyed on `evidencia`, NEVER on the EAN alone. `evidencia` is the
    canonical fingerprint of the concrete situation reviewed (see
    `tn_reconciliation_service._build_evidencia`): the verdict plus its
    operands. Accepting "this EAN with THIS SKU currently in TN" must not
    silence the product forever — if the SKU later changes to a genuinely
    wrong one, the fingerprint changes, this row stops matching, and the
    anomaly comes back for review. An exception covers exactly what was
    looked at and nothing more.

    Accepted rows are still RETURNED by the report, flagged as accepted: a
    row that vanished is indistinguishable from one that never existed, and
    a year from now nobody could tell "reviewed and fine" from "somebody
    hid it".
    """

    __tablename__ = "tn_reconcile_excepcion"

    id = Column(Integer, primary_key=True, index=True)
    # Kept for search/reporting only — it is NOT the key. See the class
    # docstring on why binding to the EAN would be unsafe.
    ean = Column(String(100), index=True, nullable=False)
    verdict = Column(String(32), nullable=False)
    evidencia = Column(Text, nullable=False, index=True)
    # Mandatory: an exception without a stated reason is indistinguishable
    # from someone silencing an alert they did not understand.
    motivo = Column(Text, nullable=False)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", backref="tn_reconcile_excepciones")

    __table_args__ = (UniqueConstraint("evidencia", name="uq_tn_reconcile_excepcion_evidencia"),)

    def __repr__(self):
        return f"<TnReconcileExcepcion(ean={self.ean}, verdict={self.verdict})>"
