"""Local categories and subcategories master (abm-productos S11): one row per GBP category/subcategory with the same id,
plus own ones. `nombre` NULL means "follow GBP's name" (`tb_category.cat_desc` / `tb_subcategory.subcat_desc`); a value
is a local override that never goes back to GBP. Rows are never deleted, only deactivated. Each one may link to a Tienda
Nube category (`tn_category_embedding.tn_category_id`); a subcategory without its own link uses its category's.
Seeded by `services.producto_categorias.sembrar_desde_gbp` on every ERP master sync."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.sql import func

from app.core.database import Base

# Own (non-GBP) categories, subcategories and brands take ids from here up, so a later GBP id never collides with one.
PRIMER_ID_PROPIO = 1_000_000


class ProductoCategoria(Base):
    __tablename__ = "producto_categorias"

    id = Column(Integer, primary_key=True, autoincrement=False)
    nombre = Column(String(255))
    activa = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    propia = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    tn_category_id = Column(Integer)
    updated_by = Column(Integer)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductoSubcategoria(Base):
    __tablename__ = "producto_subcategorias"

    id = Column(Integer, primary_key=True, autoincrement=False)
    categoria_id = Column(Integer, ForeignKey("producto_categorias.id"), nullable=False, index=True)
    nombre = Column(String(255))
    activa = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    propia = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    tn_category_id = Column(Integer)
    updated_by = Column(Integer)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
