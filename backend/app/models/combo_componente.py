"""`combo_componentes`: the app-owned combo bill of materials (combos-propios C1).

One row per (combo, component) pair: the combo item `combo_item_id` is made of
`cantidad` units of `componente_item_id`. Readers use this table instead of an
ERP mirror, so the ERP can be replaced without changing what a combo is.

It knows nothing about where the data comes from: the migration that creates it
fills it once from the ERP mirror, and a sync handler that keeps it up to date
from a source adapter comes in a following change. There is no foreign key to
the ERP mirror tables on purpose. A pair is stored once and its quantity is
always positive; a source row with no positive quantity is not a component and
is never stored.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, Numeric
from sqlalchemy.sql import func

from app.core.database import Base


class ComboComponente(Base):
    __tablename__ = "combo_componentes"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_combo_componentes_cantidad_positiva"),
        # Reverse lookup: which combos use a component.
        Index("ix_combo_componentes_componente_item_id", "componente_item_id"),
    )

    combo_item_id = Column(Integer, primary_key=True, autoincrement=False)
    componente_item_id = Column(Integer, primary_key=True, autoincrement=False)
    cantidad = Column(Numeric(18, 4), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<ComboComponente(combo={self.combo_item_id}, componente={self.componente_item_id}, "
            f"cantidad={self.cantidad})>"
        )
