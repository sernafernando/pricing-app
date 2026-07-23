from sqlalchemy import Column, Integer, ForeignKey, DateTime, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TnMarkedForDeletion(Base):
    """EAN-keyed "marked for deletion" flag.

    Slice 1 is model-only: the DB column/table exists so the mark can persist,
    but no delete-execution wiring exists yet (that's Slice 4, gated by the
    separate `tn.eliminar` permission). Auto-clear when the EAN disappears
    from GBP report 78, or manual untoggle, are both Slice 2 concerns.
    """

    __tablename__ = "tn_marked_for_deletion"

    id = Column(Integer, primary_key=True, index=True)
    ean = Column(String(100), unique=True, index=True, nullable=False)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", backref="tn_marcados_para_borrar")

    def __repr__(self):
        return f"<TnMarkedForDeletion(ean={self.ean})>"
