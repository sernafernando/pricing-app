"""Per-MLA hay_mejores application criteria (PM policy), keyed by MLA.

Sparse upsert: missing row = defaults (C1/C2/Auto off). No FK to
`ml_items` — the publication store owns that table and must not be blocked
by policy rows (same shape as `ml_item_overrides`).
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class MlHayMejoresCriterios(Base):
    __tablename__ = "ml_hay_mejores_criterios"

    item_id = Column(Text, primary_key=True)  # MLA

    # C1 — markup band (same basis as status-quo comparison). Null = side unused.
    c1_activo = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    c1_markup_min = Column(Numeric(12, 4), nullable=True)
    c1_markup_max = Column(Numeric(12, 4), nullable=True)

    # C2 — win catalog
    c2_activo = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    c2_solo_markup_positivo = Column(Boolean, nullable=False, server_default=text("true"), default=True)

    # R-AUTO
    auto_aplicacion = Column(Boolean, nullable=False, server_default=text("false"), default=False)

    # P2: unchecked competitor item_ids (absent = checked / counts).
    # Dialect-neutral default on purpose (same as ml_catalog_competition.competitors):
    # migration DDL keeps '[]'::jsonb; Base.metadata.create_all() on SQLite must not
    # emit "::jsonb" or the whole suite dies with "unrecognized token: :".
    sellers_excluidos = Column(JSONB, nullable=False, server_default="[]", default=list)

    updated_by = Column(Integer, nullable=True)  # usuarios.id
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
