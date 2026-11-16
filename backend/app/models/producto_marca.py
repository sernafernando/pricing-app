"""Local brands master (abm-productos L10): one row per GBP brand (`tb_brand.brand_id`, same id) plus own ones from
`PRIMER_ID_PROPIO` up. `nombre` NULL follows GBP's `brand_desc`; a value is a local override. Never deleted, only
deactivated. Seeded by `services.producto_categorias.sembrar_desde_gbp` on every ERP master sync."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, text
from sqlalchemy.sql import func

from app.core.database import Base


class ProductoMarca(Base):
    __tablename__ = "producto_marcas"

    id = Column(Integer, primary_key=True, autoincrement=False)
    nombre = Column(String(255))
    activa = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    propia = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    updated_by = Column(Integer)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
