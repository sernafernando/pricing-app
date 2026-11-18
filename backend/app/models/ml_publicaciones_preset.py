"""Publicaciones ML column layouts and presets (S2, S3, S4).

- `MlPublicacionesLayout`: one row per user and view (`vista`) with the column layout the user last left
  (visibility + order, NULL = the view's defaults) and the preset they last applied (`preset_activo_id`, NULL when
  none or when the preset was deleted).
- `MlPublicacionesPreset`: a named snapshot of a view's columns and URL params. `usuario_id` is the owner of a
  personal preset; NULL means shared (visible to everyone with access to the view, written only with
  `ml_publicaciones.presets_compartidos`). Names are unique case-insensitively per owner and view for personal
  presets and per view for shared ones (two partial unique indexes on `lower(nombre)`).

The payloads are validated by `app.schemas.ml_publicaciones_presets` before they get here; the database stores
them opaquely.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class MlPublicacionesPreset(Base):
    """A named column + filter preset of one Publicaciones ML view (personal or shared)."""

    __tablename__ = "ml_publicaciones_presets"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True)  # NULL = shared
    vista = Column(String(20), nullable=False)
    nombre = Column(String(60), nullable=False)
    payload = Column(JSONB, nullable=False)  # PresetPayload: {columns: {visibility, order}, params}
    created_by = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class MlPublicacionesLayout(Base):
    """The column layout and remembered preset of one user in one Publicaciones ML view."""

    __tablename__ = "ml_publicaciones_layouts"
    __table_args__ = (UniqueConstraint("usuario_id", "vista", name="uq_ml_publicaciones_layouts_usuario_vista"),)

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    vista = Column(String(20), nullable=False)
    # Python name differs from the column's: `columns` reads too close to SQLAlchemy's own table attributes.
    column_layout = Column("columns", JSONB(none_as_null=True), nullable=True)  # ColumnLayout or NULL = defaults
    preset_activo_id = Column(
        Integer, ForeignKey("ml_publicaciones_presets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


_PERSONAL = MlPublicacionesPreset.usuario_id.isnot(None)
_SHARED = MlPublicacionesPreset.usuario_id.is_(None)

Index(
    "uq_ml_publicaciones_presets_personal_nombre",
    MlPublicacionesPreset.usuario_id,
    MlPublicacionesPreset.vista,
    func.lower(MlPublicacionesPreset.nombre),
    unique=True,
    postgresql_where=_PERSONAL,
    sqlite_where=_PERSONAL,
)
Index(
    "uq_ml_publicaciones_presets_compartido_nombre",
    MlPublicacionesPreset.vista,
    func.lower(MlPublicacionesPreset.nombre),
    unique=True,
    postgresql_where=_SHARED,
    sqlite_where=_SHARED,
)
Index("ix_ml_publicaciones_presets_vista_usuario", MlPublicacionesPreset.vista, MlPublicacionesPreset.usuario_id)
