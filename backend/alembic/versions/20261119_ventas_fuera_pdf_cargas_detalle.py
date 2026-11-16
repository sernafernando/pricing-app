"""ventas por fuera PDF uploads: per-upload result columns for the upload history

Revision ID: 20261119_ventas_fuera_pdf_cargas_detalle
Revises: 20261119_vpf_offsets_sell_pdf
Create Date: 2026-11-16

Additive (vpf-metricas-canal-fe S8): nullable columns on `ventas_fuera_pdf_cargas` filled at upload with what the
upload result and the upload history show (the salespeople imported, lines, units, totals, "sin producto" lines, the
cheque surcharge, documents per type, the summary cross-check and when the upload it replaced was made). Rows uploaded before this migration keep them
NULL (the screen shows '—'). No data change; downgrade drops only these columns.

Release order #2300 -> T4 (#2302) -> this: it follows T4's 20261119_vpf_offsets_sell_pdf.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_ventas_fuera_pdf_cargas_detalle"
down_revision: Union[str, None] = "20261119_vpf_offsets_sell_pdf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "ventas_fuera_pdf_cargas"
COLUMNAS = [
    ("vendedores", sa.JSON),
    ("lineas", sa.Integer),
    ("unidades", lambda: sa.Numeric(18, 2)),
    ("total_lineas", lambda: sa.Numeric(18, 2)),
    ("sin_producto_lineas", sa.Integer),
    ("sin_producto_monto", lambda: sa.Numeric(18, 2)),
    ("recargo_financiero", lambda: sa.Numeric(18, 2)),
    ("documentos_por_tipo", sa.JSON),
    ("control", sa.JSON),
    ("control_estado", lambda: sa.String(20)),
    ("carga_anterior_at", lambda: sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for nombre, tipo in COLUMNAS:
        op.add_column(TABLA, sa.Column(nombre, tipo(), nullable=True))


def downgrade() -> None:
    for nombre, _ in reversed(COLUMNAS):
        op.drop_column(TABLA, nombre)
