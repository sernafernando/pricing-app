"""compras 012 — seed tolerancias reconciliación CC por moneda

Revision ID: compras_012_seed_config
Revises: compras_011_seed_caja_tp
Create Date: 2026-04-17

Inserta 2 claves de configuración para las tolerancias de reconciliación
diaria CC (libro mayor propio vs snapshot ERP), separadas por moneda:
  - compras.cc_reconciliacion_tolerancia_ars = 100.00
  - compras.cc_reconciliacion_tolerancia_usd = 1.00

Cierre 2 del usuario: tolerancia POR MONEDA (no una sola ARS). El job de
reconciliación (design §8.2, COMPRAS-3.6) lee la clave con sufijo según
la moneda del saldo reconciliado.

Schema real (verificado en app/models/configuracion.py):
  clave (PK VARCHAR(100)), valor (TEXT NOT NULL), descripcion (TEXT),
  tipo (VARCHAR(50) default 'string'), fecha_modificacion
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_012_seed_config"
down_revision: Union[str, None] = "compras_011_seed_caja_tp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONFIG_NUEVAS: tuple[dict, ...] = (
    {
        "clave": "compras.cc_reconciliacion_tolerancia_ars",
        "valor": "100.00",
        "tipo": "decimal",
        "descripcion": (
            "Tolerancia en ARS para diferencias entre libro mayor propio "
            "y snapshot CC. Por encima de este umbral se dispara alerta."
        ),
    },
    {
        "clave": "compras.cc_reconciliacion_tolerancia_usd",
        "valor": "1.00",
        "tipo": "decimal",
        "descripcion": ("Tolerancia en USD para diferencias entre libro mayor propio y snapshot CC."),
    },
)


def upgrade() -> None:
    conn = op.get_bind()

    insert_sql = sa.text(
        """
        INSERT INTO configuracion (clave, valor, tipo, descripcion)
        VALUES (:clave, :valor, :tipo, :descripcion)
        ON CONFLICT (clave) DO NOTHING
        """
    )
    for config in _CONFIG_NUEVAS:
        conn.execute(insert_sql, config)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM configuracion WHERE clave = ANY(:claves)"),
        {"claves": [c["clave"] for c in _CONFIG_NUEVAS]},
    )
