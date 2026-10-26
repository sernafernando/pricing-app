"""A publication's data overridden locally (Publicaciones ML T8), keyed by its MLA.

Field by field: NULL follows ML (the last read of the publication), a value overrides it. Editing never writes to ML:
pushing the override there is a separate action. The original stays where the publication store keeps it
(`ml_items.raw`, `ml_item_descriptions`), so every reader can show both. No foreign key to `ml_items`: the store's
sweeps own that table and must never be blocked by a row here.
"""

from sqlalchemy import Column, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class MlItemOverride(Base):
    __tablename__ = "ml_item_overrides"

    item_id = Column(Text, primary_key=True)  # the MLA
    titulo = Column(Text, nullable=True)
    descripcion = Column(Text, nullable=True)  # '' overrides with no description
    fotos = Column(JSONB, nullable=True)  # [{id, url}] kept from the publication's, in the new order
    atributos = Column(JSONB, nullable=True)  # [{id, name, value_name}] kept from the publication's, with new values
    updated_by = Column(Integer, nullable=True)  # usuarios.id
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
