"""proveedor_direcciones.numero: número de calle separado de la calle

Revision ID: 20261015_proveedor_direccion_numero
Revises: 20261014_ml_ads_account_level
Create Date: 2026-10-09

`proveedor_direcciones.direccion` guardaba calle + número juntos ("Brasil 2669"), y la etiqueta
de retiro (etiqueta_retiro_service) dejaba `manual_street_number` vacío. Se agrega `numero` y se
backfillea por regex (preview en prod 2026-10-09: 10/10 filas OK). Las filas que no matchean, o
cuyo "número" es en realidad de ruta/km/autopista, quedan intactas con `numero` NULL.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261015_proveedor_direccion_numero"
down_revision: Union[str, None] = "20261014_ml_ads_account_level"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# m[1] = calle, m[2] = número, m[3] = resto opcional tras una coma (piso/depto).
PATRON_DIRECCION = r"^\s*(.*?)[\s,]+(?:n[°ºo]?\.?\s*|nro\.?\s*|n[uú]mero\s*)?(\d{1,6}[a-zA-Z]?)\s*(?:,\s*(.*))?$"

# Calles cuyo "número" no es altura: "Ruta 8", "Km 45", "Autopista 1", "Calle 12".
PATRON_NO_ALTURA = r"(^|\s)(ruta|rn|rp|km|kil[oó]metro|autopista|calle)\.?$"


def upgrade() -> None:
    op.add_column("proveedor_direcciones", sa.Column("numero", sa.String(50), nullable=True))

    # regexp_match es Postgres-only; los tests corren sobre SQLite y no tienen filas que migrar.
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            UPDATE proveedor_direcciones AS pd
            SET direccion = CASE
                    WHEN NULLIF(trim(x.m[3]), '') IS NOT NULL
                        THEN trim(x.m[1]) || ', ' || trim(x.m[3])
                    ELSE trim(x.m[1])
                END,
                numero = x.m[2]
            FROM (
                SELECT id, regexp_match(direccion, :patron, 'i') AS m
                FROM proveedor_direcciones
                WHERE numero IS NULL
            ) AS x
            WHERE pd.id = x.id
              AND x.m IS NOT NULL
              AND x.m[1] ~ '[a-zA-Z]'
              AND x.m[1] !~* :no_altura
            """
        ).bindparams(patron=PATRON_DIRECCION, no_altura=PATRON_NO_ALTURA)
    )


def downgrade() -> None:
    # Vuelve a pegar el número a la calle. Si había sufijo (", piso 3") queda antes del número:
    # aceptable, el dato no se pierde.
    op.execute(
        sa.text("UPDATE proveedor_direcciones SET direccion = direccion || ' ' || numero WHERE numero IS NOT NULL")
    )
    op.drop_column("proveedor_direcciones", "numero")
