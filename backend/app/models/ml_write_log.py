"""Record of every write WE made to MercadoLibre (eventos-historial-legibles T2).

One row per confirmed write: who did it (`usuario_id`, NULL for system or
worker writes), to which item (`mla`), what (`resource` + `action`), against
which target (`target_id`, e.g. the promotion id) and with what we sent
(`payload`). The Publicaciones ML panel correlates its events with these rows
to tell "done by us" apart from "done by ML".

Rows are written only AFTER ML confirmed the write. Writes that already have
their own audit trail (PxQ price -> `auditoria` PXQ_PRECIO_PUBLICADO, free
shipping -> `free_shipping_fix_log`, links -> `auditoria` ML_VINCULO_*) are
NOT duplicated here: one source per fact.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

RESOURCE_PROMOTION = "promotion"
ACTION_ENROLL = "enroll"
ACTION_REMOVE = "remove"
RESOURCE_ITEM = "item"
ACTION_PAUSE = "pause"
ACTION_ACTIVATE = "activate"
# The publication override pushed to ML (Publicaciones ML T8c): the item fields, and the description apart.
ACTION_UPDATE_DATA = "update_data"
ACTION_UPDATE_DESCRIPTION = "update_description"


class MlWriteLog(Base):
    """One confirmed write to ML, with the user who caused it."""

    __tablename__ = "ml_write_log"

    id = Column(Integer, primary_key=True)
    mla = Column(String(32), nullable=False)
    resource = Column(String(40), nullable=False)
    action = Column(String(40), nullable=False)
    target_id = Column(String(100), nullable=True)
    promotion_type = Column(String(40), nullable=True)
    payload = Column(JSONB, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_ml_write_log_mla_created_at", "mla", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<MlWriteLog mla={self.mla!r} {self.resource}.{self.action} usuario_id={self.usuario_id!r}>"
