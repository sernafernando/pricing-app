"""Technical specs of a product (abm-specs-productos S3): one row per ERP `item_id`, one typed column per field.

Numeric fields are numbers in a fixed unit; categorical fields hold one value of that field's normalized list
(`producto_spec_valores`), so the later Publicaciones ML view can filter and sort on plain indexed columns. `origenes`
remembers where each field came from (`ml`, `erp_name`, `combo`, `manual`); a pre-load never touches a `manual` one.
No foreign key to `productos_erp`: the ERP sync owns that table and must never be blocked by a row here.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.services.producto_specs.campos import CATEGORICOS, NUMERICOS

MAX_VALOR_LENGTH = 120

# Each field is indexed: the later Publicaciones ML view filters and sorts by any of them.
INDEXED_COLUMNS = ("tipo", *NUMERICOS, *CATEGORICOS)


class ProductoSpec(Base):
    __tablename__ = "producto_specs"
    __table_args__ = (CheckConstraint("tipo IN ('notebook', 'pc')", name="ck_producto_specs_tipo"),)

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    tipo = Column(String(20), nullable=False)

    cpu_marca = Column(String(MAX_VALOR_LENGTH))
    cpu_linea = Column(String(MAX_VALOR_LENGTH))
    cpu_modelo = Column(String(MAX_VALOR_LENGTH))
    ram_gb = Column(Integer)
    ram_tipo = Column(String(MAX_VALOR_LENGTH))
    pantalla_pulgadas = Column(Numeric(4, 1))
    pantalla_resolucion = Column(String(MAX_VALOR_LENGTH))
    pantalla_panel = Column(String(MAX_VALOR_LENGTH))
    pantalla_hz = Column(Integer)
    disco_gb = Column(Integer)
    disco_tipo = Column(String(MAX_VALOR_LENGTH))
    so_nombre = Column(String(MAX_VALOR_LENGTH))
    so_edicion = Column(String(MAX_VALOR_LENGTH))
    gpu_tipo = Column(String(MAX_VALOR_LENGTH))
    gpu_marca = Column(String(MAX_VALOR_LENGTH))
    gpu_modelo = Column(String(MAX_VALOR_LENGTH))
    gpu_vram_gb = Column(Integer)
    gabinete_marca = Column(String(MAX_VALOR_LENGTH))
    gabinete_modelo = Column(String(MAX_VALOR_LENGTH))
    fuente_marca = Column(String(MAX_VALOR_LENGTH))
    fuente_modelo = Column(String(MAX_VALOR_LENGTH))
    fuente_watts = Column(Integer)
    mother_marca = Column(String(MAX_VALOR_LENGTH))
    mother_modelo = Column(String(MAX_VALOR_LENGTH))
    refrigeracion_tipo = Column(String(MAX_VALOR_LENGTH))
    refrigeracion_marca = Column(String(MAX_VALOR_LENGTH))
    refrigeracion_modelo = Column(String(MAX_VALOR_LENGTH))

    origenes = Column(JSONB, nullable=False, server_default="{}")  # {field: ml | erp_name | combo | manual | no_aplica}
    fuente_mla = Column(Text)  # the ML publication the `ml` fields came from (the winner, see the pre-load)
    precargado_at = Column(DateTime(timezone=True))
    updated_by = Column(Integer)  # usuarios.id of the last manual edit
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProductoSpecValor(Base):
    """One value of a categorical field's normalized list. `clave` (case- and spacing-folded) is its identity, so
    "16 gb" and "16 GB" are one value; `valor` is how it is shown."""

    __tablename__ = "producto_spec_valores"

    campo = Column(String(40), primary_key=True)
    clave = Column(String(MAX_VALOR_LENGTH), primary_key=True)
    valor = Column(String(MAX_VALOR_LENGTH), nullable=False)
    created_by = Column(Integer)  # usuarios.id; NULL: seeded or found by the pre-load
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
