from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class TnCategoryProfileHint(Base):
    """Per-(categoria, subcategoria) usage-count hint for measurement-profile
    suggestion (MP3). On a successful publish where a profile was applied,
    the row for `(categoria, subcategoria, profile_id)` is upserted with
    `uso_count += 1`. Suggestion picks the highest `uso_count` for an exact
    `(categoria, subcategoria)` match, else `(categoria, NULL)`, else none —
    cold start (no rows) returns none, per MP3's "empty result, not an
    error" scenario.
    """

    __tablename__ = "tn_category_profile_hint"
    __table_args__ = (UniqueConstraint("categoria", "subcategoria", "profile_id", name="uq_tn_category_profile_hint"),)

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(150), nullable=False, index=True)
    subcategoria = Column(String(150), nullable=True)

    profile_id = Column(Integer, ForeignKey("tn_measurement_profile.id", ondelete="CASCADE"), nullable=False)
    uso_count = Column(Integer, nullable=False, default=0, server_default="0")

    profile = relationship("TnMeasurementProfile")

    def __repr__(self):
        return f"<TnCategoryProfileHint(categoria={self.categoria}, subcategoria={self.subcategoria})>"
