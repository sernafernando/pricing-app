from sqlalchemy import Column, Integer, ForeignKey, DateTime, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TnReconcileResolution(Base):
    """EAN-keyed human resolution/ignore flag for the TN reconciliation view.

    Lets an operator record that a given anomaly (e.g. a reviewed DUPLICADO
    group) has been looked at, without altering the live-recomputed verdict
    itself. Slice 1 creates the table only; no endpoint writes to it yet.
    """

    __tablename__ = "tn_reconcile_resolution"

    id = Column(Integer, primary_key=True, index=True)
    ean = Column(String(100), unique=True, index=True, nullable=False)
    nota = Column(Text, nullable=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", backref="tn_reconcile_resoluciones")

    def __repr__(self):
        return f"<TnReconcileResolution(ean={self.ean})>"
