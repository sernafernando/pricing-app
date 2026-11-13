"""Teams (equipos) for per-team product color marking.

Introduces:
- `Equipo`: a team; a single sentinel row (`es_global=True`) represents the
  legacy "global" scope so existing color data can be backfilled without a
  behavior change (PR1 is models + migration only, no endpoints yet).
- `EquipoMiembro`: membership of a `Usuario` in an `Equipo`, with a role and the member's own layer preferences.
- `ProductoColor`: per-team color marking for a `ProductoERP`, replacing the
  single global `productos_pricing.color_marcado`/`color_marcado_tienda`
  columns (retained for now; migration only backfills into this new table).
- `PublicacionColor`: per-team ML color of one publication (MLA), painted from
  Publicaciones ML. It overrides its product's `ProductoColor.color_ml` in that
  layer; without a row the publication shows its product's color.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class RolEquipo(str, enum.Enum):
    ADMIN = "admin"
    MIEMBRO = "miembro"


class Equipo(Base):
    __tablename__ = "equipo"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    es_global = Column(Boolean, nullable=False, default=False)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creador = relationship("Usuario", foreign_keys=[creado_por])
    miembros = relationship("EquipoMiembro", back_populates="equipo")
    colores = relationship("ProductoColor", back_populates="equipo")
    colores_publicacion = relationship("PublicacionColor", back_populates="equipo")

    __table_args__ = (
        # Guarantees a single "global" (es_global=True) team row. Partial
        # (WHERE-filtered) unique indexes are supported by both Postgres and
        # modern SQLite (>= 3.8, used by the in-memory test DB) — pass both
        # dialect kwargs so the constraint is actually enforced in tests too,
        # instead of silently becoming a full-column unique index (which
        # would incorrectly reject more than one es_global=False row).
        Index(
            "uq_equipo_es_global_singleton",
            "es_global",
            unique=True,
            postgresql_where=text("es_global"),
            sqlite_where=text("es_global"),
        ),
    )


class EquipoMiembro(Base):
    __tablename__ = "equipo_miembro"
    __table_args__ = (
        UniqueConstraint("equipo_id", "usuario_id", name="uq_equipo_miembro_equipo_usuario"),
        # At most one default layer per user (see `Equipo`'s singleton index for the dialect kwargs).
        Index(
            "uq_equipo_miembro_usuario_por_defecto",
            "usuario_id",
            unique=True,
            postgresql_where=text("por_defecto"),
            sqlite_where=text("por_defecto"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    equipo_id = Column(Integer, ForeignKey("equipo.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    # String (not SQLEnum) to avoid enum name/value drift — see alerta.py
    rol = Column(String(20), nullable=False)
    # The member's own Publicaciones ML preferences for this layer: the layer it opens on (at most one per user; none
    # marked = the global layer) and whether the global color reference shows on rows this team has not painted.
    por_defecto = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    mostrar_referencia_global = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    equipo = relationship("Equipo", back_populates="miembros")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class ProductoColor(Base):
    __tablename__ = "producto_color"
    __table_args__ = (UniqueConstraint("equipo_id", "item_id", name="uq_producto_color_equipo_item"),)

    id = Column(Integer, primary_key=True, index=True)
    equipo_id = Column(Integer, ForeignKey("equipo.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), nullable=False, index=True)
    color_ml = Column(String(20), nullable=True)
    color_tienda = Column(String(20), nullable=True)
    updated_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    equipo = relationship("Equipo", back_populates="colores")
    producto = relationship("ProductoERP")
    editor = relationship("Usuario", foreign_keys=[updated_by])


class PublicacionColor(Base):
    __tablename__ = "publicacion_color"
    __table_args__ = (UniqueConstraint("equipo_id", "item_id", name="uq_publicacion_color_equipo_item"),)

    id = Column(Integer, primary_key=True, index=True)
    equipo_id = Column(Integer, ForeignKey("equipo.id"), nullable=False, index=True)
    # The MLA. No foreign key to `ml_items`: a color may outlive its publication there (team deletion drops those).
    item_id = Column(String(30), nullable=False, index=True)
    color_ml = Column(String(20), nullable=False)
    updated_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    equipo = relationship("Equipo", back_populates="colores_publicacion")
    editor = relationship("Usuario", foreign_keys=[updated_by])
