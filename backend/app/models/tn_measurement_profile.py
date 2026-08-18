from sqlalchemy import Column, DateTime, Integer, Numeric, String
from sqlalchemy.sql import func

from app.core.database import Base


class TnMeasurementProfile(Base):
    """Reusable weight/width/height/depth box profile for TN publish drafts.

    Exists to make the `tn-publish-core` blocking gate survivable: items with
    no GBP measurements can select a profile instead of being unpublishable.
    Seeded with the four de-facto GBP box clusters
    (30x20x20, 30x40x10, 50x40x20, 45x55x25) by the profile-creating migration.
    """

    __tablename__ = "tn_measurement_profile"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    weight = Column(Numeric(10, 3), nullable=False)
    width = Column(Numeric(10, 2), nullable=False)
    height = Column(Numeric(10, 2), nullable=False)
    depth = Column(Numeric(10, 2), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<TnMeasurementProfile(id={self.id}, name={self.name})>"
