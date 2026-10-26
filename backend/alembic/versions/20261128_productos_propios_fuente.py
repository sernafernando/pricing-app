"""productos_propios: the data copied from the publication chosen as source

Revision ID: 20261128_productos_propios_fuente
Revises: 20261127_productos_propios
Create Date: 2026-10-26

Publicaciones ML T7: the product's title, description, pictures and attributes, copied from one of its publications
and edited on the product. Nullable columns only: existing rows (manual SKU / EAN) keep meaning "no source chosen".
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261128_productos_propios_fuente"
down_revision: Union[str, None] = "20261127_productos_propios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("fuente_mla", sa.Text()),
    ("titulo", sa.Text()),
    ("descripcion", sa.Text()),
    ("fotos", JSONB()),
    ("atributos", JSONB()),
    ("fuente_copiada_por", sa.Integer()),
    ("fuente_copiada_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("productos_propios", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("productos_propios", name)
