"""Our own product (Publicaciones ML T6): the manual SKU and EAN of an ERP product, keyed by its `item_id`.

Only what an operator typed is stored; the values the panel shows are computed on read
(`app.services.producto_propio_service`). When the ERP is replaced, this `item_id` becomes our own product id.
No foreign key to `productos_erp`: the ERP sync owns that table and must never be blocked by a row here.
"""

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base

# The longest SKU or EAN accepted: the width of the ERP `codigo` column the EAN defaults to.
MAX_CODE_LENGTH = 100
# A text source meaning "own text": stored on the row and fixed (product master, abm-productos T4).
FUENTE_PROPIA = "propio"


class ProductoPropio(Base):
    __tablename__ = "productos_propios"

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    sku = Column(String(MAX_CODE_LENGTH), nullable=True)  # NULL: the SKU the linked publications share
    ean = Column(String(MAX_CODE_LENGTH), nullable=True)  # NULL: the ERP `codigo`
    updated_by = Column(Integer, nullable=True)  # usuarios.id of the last SKU / EAN edit
    # The data copied from the publication chosen as source (T7): a copy, edited here, never a live link.
    fuente_mla = Column(Text, nullable=True)  # NULL: no source chosen yet
    titulo = Column(Text, nullable=True)
    descripcion = Column(Text, nullable=True)
    fotos = Column(JSONB, nullable=True)  # [{id, url}], in the publication's order
    atributos = Column(JSONB, nullable=True)  # [{id, name, value_name}], only the ones with a value
    fuente_copiada_por = Column(Integer, nullable=True)  # usuarios.id
    fuente_copiada_at = Column(DateTime(timezone=True), nullable=True)
    # Product master (abm-productos T4): overrides of GBP, NULL = follow GBP (`app.services.producto_maestro`).
    nombre = Column(String(500), nullable=True)
    codigo_fabricante = Column(String(MAX_CODE_LENGTH), nullable=True)
    marca_id = Column(Integer, nullable=True)
    categoria_id = Column(Integer, nullable=True)
    subcategoria_id = Column(Integer, nullable=True)
    garantia_dias = Column(Integer, nullable=True)
    peso_g = Column(Numeric(12, 2), nullable=True)
    ancho_cm = Column(Numeric(10, 2), nullable=True)
    largo_cm = Column(Numeric(10, 2), nullable=True)
    alto_cm = Column(Numeric(10, 2), nullable=True)
    # The texts: `titulo` / `descripcion` above are the own ML ones, these the own web ones. Each `fuente_*` is the
    # chosen source (ml, tn, gbp, nombre, propio); NULL = the default source. Only `propio` reads the stored text.
    titulo_web = Column(Text, nullable=True)
    descripcion_web = Column(Text, nullable=True)
    fuente_titulo_ml = Column(String(20), nullable=True)
    fuente_titulo_web = Column(String(20), nullable=True)
    fuente_descripcion_ml = Column(String(20), nullable=True)
    fuente_descripcion_web = Column(String(20), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
