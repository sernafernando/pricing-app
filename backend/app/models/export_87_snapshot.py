"""
Modelo para tb_export_87_snapshot
Tabla intermedia para guardar snapshots del Export 87 del ERP
"""

from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Export87Snapshot(Base):
    __tablename__ = "tb_export_87_snapshot"

    snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    soh_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer)
    comp_id = Column(Integer)

    # Campos enriquecidos del Export 87
    user_id = Column(Integer, index=True)
    order_id = Column(String(50), index=True)  # orderID de TiendaNube
    ssos_id = Column(Integer)

    # Metadata
    snapshot_date = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    export_id = Column(Integer, nullable=False, default=87)

    # JSON crudo
    raw_data = Column(JSONB)

    __table_args__ = (
        UniqueConstraint("soh_id", "snapshot_date", name="export_87_snapshot_soh_unique"),
        Index("idx_export_87_snapshot_date", "snapshot_date", postgresql_using="btree"),
    )

    def __repr__(self):
        return f"<Export87Snapshot(soh_id={self.soh_id}, snapshot_date={self.snapshot_date})>"
